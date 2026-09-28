#!/usr/bin/env python3
"""Movie render pipeline: plan → storyboard → video → assemble."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from movie_generator.agents.story_engine import StoryEngine, ContinuityFixAgent

log = logging.getLogger(__name__)


class MovieGenerator:
    """End-to-end movie generation pipeline."""

    def __init__(self, client, project_dir: str = "projects"):
        self.client = client
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.engine = StoryEngine(client)

    def generate(self, name: str, synopsis: str, num_shots: int = 20,
                 style: str = "realistic", review: bool = True) -> str:
        """Run the full generation pipeline."""
        project_path = self.project_dir / name

        # 1. Plan
        log.info("Planning story for '%s'...", name)
        plan = self.engine.plan_story(synopsis, num_shots)

        # 2. Optional continuity fix
        if review:
            plan = ContinuityFixAgent.fix_plan(plan, self.client)

        # 3. Save plan
        plan_path = project_path / "plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2))
        log.info("Plan saved to %s", plan_path)

        # 4. Flatten shots
        flat = []
        for act in plan.get("acts", []):
            for scene in act.get("scenes", []):
                for shot in scene.get("shots", []):
                    flat.append((scene, shot))

        total = len(flat)
        if total == 0:
            raise ValueError("No shots generated. Try a different synopsis.")

        log.info("Generating %d shots...", total)

        # 5. Collect location/prop info for consistency
        locations = {l.get("name", ""): l for l in plan.get("locations", [])}
        props = plan.get("props", [])

        # 6. Storyboard: generate keyframes
        log.info("Generating keyframes...")
        for i, (scene, shot) in enumerate(flat):
            shot_id = shot.get("shot_id", f"shot_{i}")
            kf_path = project_path / "storyboard" / f"{shot_id}.png"
            if kf_path.exists():
                log.info("  %s already exists, skipping", shot_id)
                continue

            prompt = self.engine.build_video_prompt(
                shot, scene, plan.get("character_bank", {}), style)
            prompt = self._inject_consistency(prompt, scene, locations, props)

            try:
                res = self.client.image(prompt, size="1280x720")
                img_url = (res.get("data") or [{}])[0].get("url")
                if img_url:
                    import requests as req
                    tmp = kf_path.with_suffix(kf_path.suffix + ".part")
                    r = req.get(img_url, timeout=300)
                    r.raise_for_status()
                    tmp.write_bytes(r.content)
                    tmp.rename(kf_path)
                    log.info("  %s keyframe saved", shot_id)
            except Exception as e:
                log.error("  %s keyframe failed: %s", shot_id, e)

        # 7. Video render
        log.info("Rendering video shots...")
        for i, (scene, shot) in enumerate(flat):
            shot_id = shot.get("shot_id", f"shot_{i}")
            out_path = project_path / "video" / f"{shot_id}.mp4"
            if out_path.exists():
                log.info("  %s video already exists, skipping", shot_id)
                continue

            kf_path = project_path / "storyboard" / f"{shot_id}.png"
            prompt = self.engine.build_video_prompt(
                shot, scene, plan.get("character_bank", {}), style)
            prompt = self._inject_consistency(prompt, scene, locations, props)

            try:
                img_url = None
                if kf_path.exists():
                    res = self.client.image(prompt, size="1280x720")
                    img_url = (res.get("data") or [{}])[0].get("url")

                url = self.client.video(prompt, num_frames=121, first_frame_url=img_url)
                import requests as req
                tmp = out_path.with_suffix(out_path.suffix + ".part")
                r = req.get(url, timeout=600)
                r.raise_for_status()
                tmp.write_bytes(r.content)
                tmp.rename(out_path)
                log.info("  %s video rendered", shot_id)
            except Exception as e:
                log.error("  %s video failed: %s", shot_id, e)

        # 8. Assemble
        log.info("Assembling final movie...")
        out = self.assemble(name, flat)
        log.info("Movie saved to %s", out)
        return str(out)

    def assemble(self, name: str, flat: list,
                 output_name: str | None = None) -> Path:
        """Concatenate all shot videos into one movie."""
        project_path = self.project_dir / name
        if output_name is None:
            output_name = name
        out = project_path / f"{output_name}.mp4"

        # Build concat file
        concat_lines = []
        video_dir = project_path / "video"
        for scene, shot in flat:
            shot_id = shot.get("shot_id", "shot")
            vid = video_dir / f"{shot_id}.mp4"
            if vid.exists():
                concat_lines.append(f"file '{vid}'")

        if not concat_lines:
            raise FileNotFoundError("No video files found to assemble")

        concat_file = project_path / "concat.txt"
        concat_file.write_text("\n".join(concat_lines))

        # Use ffmpeg to concat
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out),
        ], check=True, capture_output=True)

        return out

    @staticmethod
    def _inject_consistency(prompt: str, scene: dict,
                            locations: dict, props: list) -> str:
        """Add location and prop details to a shot prompt."""
        location = scene.get("location", "")
        if location and location in locations:
            loc_desc = locations[location].get("canonical_desc", "")
            prompt += f" Location: {loc_desc}"

        if props:
            scene_id = scene.get("scene_id", "")
            scene_props = [p for p in props if scene_id in p.get("scenes", [])]
            if scene_props:
                prop_descs = [f"{p['name']}: {p.get('description', '')}" for p in scene_props]
                prompt += " Props: " + "; ".join(prop_descs)

        return prompt

    @staticmethod
    def _extract_json(text: str) -> dict:
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not extract JSON from: {text[:200]}")

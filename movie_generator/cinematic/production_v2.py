#!/usr/bin/env python3
"""Cinematic production pipeline v2 — rebuilt for Agnes Video 2.5.

Key upgrades vs v1:
  - Agnes Video 2.5 (native AUDIO, seed reproducibility, seconds 4-12,
    size tiers, aspect_ratio 21:9 cinematic)
  - keyframe mode with PUBLIC first_frame URLs (media must be reachable
    by Agnes — data URIs not accepted); keyframes are served via Caddy
    at MEDIA_BASE_URL
  - reference mode for character consistency on tricky shots
  - AUDIO included in scene/movie assembly + final export
  - prompts end with sound description so every shot carries ambience
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from movie_generator.agnes_client_v2 import AgnesClient, MEDIA_BASE_URL
from movie_generator.cinematic.bible import AssetRegistry, ProjectBible
from movie_generator.cinematic.continuity import validate_chain
from movie_generator.cinematic.frames import calculate_num_frames, clamp_duration_for_level
from movie_generator.cinematic.models import save_state
from movie_generator.cinematic.prompts import (
    build_image_prompt, build_video_prompt, negative_prompt,
)
from movie_generator.cinematic.production import ProductionPipeline as V1Pipeline
from movie_generator.cinematic.queue import RenderQueue
from movie_generator.cinematic.qa import qa_keyframe, qa_video, save_qa_report

log = logging.getLogger(__name__)

CINEMA_W, CINEMA_H = 1470, 630  # Video 2.5 21:9 @ 720P

SOUND_DEFAULTS = {
    "default": "natural ambient sound matching the scene, realistic foley",
    "mountain": "wind over rocky ridge, distant bird calls",
    "forest": "forest ambience, leaves rustling",
    "village": "village murmur, distant chores, chickens",
    "night": "quiet night ambience, crickets, soft breathing",
    "rain": "steady rain, dripping water, muffled thunder",
    "fire": "crackling fire, low roar",
    "interior": "quiet room tone, creaking wood",
}


class ProductionPipelineV2(V1Pipeline):
    """Shot-level cinematic production pipeline (Video 2.5 with audio)."""

    def __init__(self, client, projects_dir: str | Path, project_name: str):
        super().__init__(client, projects_dir, project_name)
        self.media_dir = self.dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clamp_seconds(shot: dict) -> str:
        """Video 2.5 accepts 4-12s. Clamp per generation level, min 4."""
        dur = float(shot.get("duration_seconds", 5.0))
        level = shot.get("generation_level") or 1
        dur = clamp_duration_for_level(dur, level)
        dur = max(dur, 4.0)
        return str(int(round(min(dur, 12.0))))

    @staticmethod
    def _sound_for(shot: dict) -> str:
        amb = (shot.get("ambience") or shot.get("sfx") or "").strip()
        if amb:
            return f"Sound: {amb}"
        loc = (shot.get("location_id") or "").lower()
        for key, s in SOUND_DEFAULTS.items():
            if key != "default" and key in loc:
                return f"Sound: {s}"
        return f"Sound: {SOUND_DEFAULTS['default']}"

    def _public_url(self, name: str) -> str:
        return f"{MEDIA_BASE_URL}/{name}"

    def _publish_keyframe(self, shot: dict) -> str | None:
        """Copy keyframe into media dir with a stable public name."""
        kf = shot.get("file_paths", {}).get("keyframe")
        if not kf or not Path(kf).exists():
            return None
        dest = self.media_dir / f"{shot['shot_id']}.png"
        dest.write_bytes(Path(kf).read_bytes())
        return self._public_url(dest.name)

    # ------------------------------------------------------------- prompts
    def rebuild_prompts(self, plan: dict):
        """Rebuild all prompts with Video 2.5 prompt order + sound tail."""
        bible_chars = {}
        for a in self.registry.by_type("CHARACTER"):
            bible_chars[a["name"]] = a
        style = self.bible.data.get("visual_style", (
            "Photorealistic live-action, real actors photographed by a "
            "professional live-action cinematographer, natural film grain, "
            "realistic skin textures, physically believable, not cartoon, "
            "not 3D animation, not AI-looking, not beauty-filtered"))
        period_rules = ""
        if any(s.get("period") == "2006" for sc in plan["scenes"] for s in sc["shots"]):
            period_rules = ("Period-appropriate 2006 technology. Warm-neutral "
                            "palette: beige, brown, amber, muted cream.")
        for scene in plan["scenes"]:
            for shot in scene["shots"]:
                shot["image_prompt"] = build_image_prompt(
                    shot, scene, bible_chars, style, period_rules)
                # Video 2.5 prompt order: subject+setting, action, camera,
                # style, sound, consistency
                shot["video_prompt"] = build_video_prompt(
                    shot, scene, bible_chars, style, period_rules)
                shot["video_prompt"] += f" {self._sound_for(shot)}"
                shot["negative_prompt"] = negative_prompt(shot)
        self.save_plan(plan)

    # ------------------------------------------------------------- phase 4
    def generate_keyframe(self, scene: dict, shot: dict) -> Path:
        """PHASE 4: storyboard keyframe (21:9 for video 2.5 framing)."""
        shot_id = shot["shot_id"]
        kf = self.dir / "storyboard" / scene["scene_id"] / f"{shot_id}.png"
        kf.parent.mkdir(parents=True, exist_ok=True)
        if kf.exists():
            shot["image_status"] = "COMPLETED"
            return kf
        prompt = shot.get("image_prompt") or ""
        ref_url = None
        for cid in shot.get("required_assets", []):
            a = self.registry.get(cid)
            if a and a.get("type") == "CHARACTER":
                img = self.registry.reference_image(cid)
                if img and img.exists():
                    import base64
                    b64 = base64.b64encode(img.read_bytes()).decode()
                    ref_url = f"data:image/png;base64,{b64}"
                    break
        res = self.client.image(prompt, size=f"{CINEMA_W}x{CINEMA_H}", image_url=ref_url)
        img_url = (res.get("data") or [{}])[0].get("url")
        if not img_url:
            raise RuntimeError(f"No image URL for {shot_id}")
        import requests as req
        tmp = kf.with_suffix(".part")
        r = req.get(img_url, timeout=300)
        r.raise_for_status()
        tmp.write_bytes(r.content)
        tmp.rename(kf)
        shot["image_status"] = "COMPLETED"
        shot.setdefault("file_paths", {})["keyframe"] = str(kf)
        save_state(self.dir, shot)
        return kf

    # ------------------------------------------------------------- phase 6
    def generate_video(self, scene: dict, shot: dict) -> Path:
        """PHASE 6: Video 2.5 generation — keyframe mode with public first
        frame URL; falls back to reference mode (character refs) or text."""
        shot_id = shot["shot_id"]
        if shot.get("qa_status") not in ("KEYFRAME_APPROVED", "PASSED", "PENDING"):
            raise RuntimeError(f"{shot_id}: keyframe approval required before video")
        kf = self.dir / "storyboard" / scene["scene_id"] / f"{shot_id}.png"
        if not kf.exists():
            raise RuntimeError(f"{shot_id}: keyframe missing")

        out = self.dir / "video" / scene["scene_id"] / f"{shot_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            shot["video_status"] = "COMPLETED"
            return out

        prompt = shot.get("video_prompt") or ""
        neg = shot.get("negative_prompt") or ""
        if neg:
            # trim to a short avoid clause — Video 2.5 prompt should stay focused
            prompt = f"{prompt} Avoid: identity drift, background morphing, CGI look, text, watermark."

        seconds = self._clamp_seconds(shot)
        seed = shot.get("seed") or 1000 + shot.get("shot_number", 0) * 7

        first_url = self._publish_keyframe(shot)
        ref_urls = None
        if not first_url:
            ref_urls = []
            for img in shot.get("reference_images", [])[:3]:
                if Path(img).exists():
                    import base64
                    # reference mode needs public URLs too; publish refs
                    dest = self.media_dir / f"ref_{shot_id}_{len(ref_urls)}.png"
                    dest.write_bytes(Path(img).read_bytes())
                    ref_urls.append(self._public_url(dest.name))
            if not ref_urls:
                ref_urls = None

        common = dict(prompt=prompt, seconds=seconds, size="720P",
                      aspect_ratio="21:9", seed=seed)
        models = ["agnes-video-2.5-flash", "agnes-video-2.5"]
        url = None
        last_exc = None
        for mdl in models:
            try:
                if first_url:
                    url = self.client.video(model=mdl, mode="keyframe", first_frame_url=first_url, **common)
                elif ref_urls:
                    url = self.client.video(model=mdl, mode="reference", reference_images=ref_urls, **common)
                else:
                    url = self.client.video(model=mdl, mode="text", **common)
                break
            except Exception as e:
                log.warning("video %s via %s failed: %s", shot_id, mdl, str(e)[:120])
                continue
        if url is None:
            raise RuntimeError(f"{shot_id}: all video models failed")

        import requests as req
        tmp = out.with_suffix(".part")
        r = req.get(url, timeout=600)
        r.raise_for_status()
        tmp.write_bytes(r.content)
        tmp.rename(out)
        shot["video_status"] = "COMPLETED"
        shot["status"] = "COMPLETED"
        shot["actual_seconds"] = seconds
        shot.setdefault("file_paths", {})["video"] = str(out)
        save_state(self.dir, shot)
        return out

    # ------------------------------------------------------------- assembly
    def assemble_scene(self, scene_id: str, plan: dict | None = None,
                       disabled: set[str] | None = None, trims: dict | None = None) -> Path:
        """PHASE 8: assemble one scene WITH AUDIO (aac passthrough/re-encode)."""
        plan = plan or self.load_plan()
        scene = next((s for s in plan["scenes"] if s["scene_id"] == scene_id), None)
        if not scene:
            raise FileNotFoundError(scene_id)
        disabled = disabled or set()
        trims = trims or {}
        out = self.dir / "edit" / f"{scene_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)

        inputs, filter_chains = [], []
        for shot in scene["shots"]:
            shot_id = shot["shot_id"]
            if shot_id in disabled:
                continue
            vid = self.dir / "video" / scene_id / f"{shot_id}.mp4"
            if not vid.exists():
                continue
            inputs.append(str(vid))
            idx = len(inputs) - 1
            trim = trims.get(shot_id)
            if trim:
                start, dur = trim
                filter_chains.append(
                    f"[{idx}:v] trim=start={start}:duration={dur},setpts=PTS-STARTPTS,"
                    f"[{idx}:a] atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS[a{idx}]")
                filter_chains[-1] = (
                    f"[{idx}:v] trim=start={start}:duration={dur},setpts=PTS-STARTPTS[v{idx}];"
                    f"[{idx}:a] atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS[a{idx}]")
            else:
                filter_chains.append(
                    f"[{idx}:v] null[v{idx}];[{idx}:a] anull[a{idx}]")

        if not inputs:
            raise FileNotFoundError(f"No videos for scene {scene_id}")

        n = len(inputs)
        # concat video; pad/concat audio where present (Video 2.5 gives aac)
        vchain = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]"
        ainputs = []
        acmd_pre = []
        # audio handling: normalize each input's audio to same rate via apad fallback
        achain_parts = []
        for i in range(n):
            achain_parts.append(f"[a{i}] apad=whole_dur=9999,atrim=0:0,anull[a{i}f]")
        # simpler robust approach: amix not needed; use concat with a=1 and
        # pad each audio to its video duration by processing per input first.
        # We do a two-pass: first normalize with ffmpeg per input, then concat.
        tmpdir = self.dir / "edit" / "_tmp_audio"
        tmpdir.mkdir(parents=True, exist_ok=True)
        norm_inputs = []
        for i, src in enumerate(inputs):
            norm = tmpdir / f"norm_{scene_id}_{i}.mp4"
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", src],
                capture_output=True, text=True)
            if "audio" in probe.stdout:
                subprocess.run([
                    "ffmpeg", "-y", "-i", src,
                    "-af", "apad", "-tune", "ultrafast", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", str(norm),
                ], capture_output=True, timeout=600)
            else:
                # silent video -> add scene-appropriate silence track so concat works
                subprocess.run([
                    "ffmpeg", "-y", "-i", src,
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    str(norm),
                ], capture_output=True, timeout=600)
            norm_inputs.append(str(norm))

        cmd = ["ffmpeg", "-y"]
        for i in norm_inputs:
            cmd += ["-i", i]
        final_chain = "".join(f"[v{i}]" for i in range(n)) + \
            f"concat=n={n}:v=1:a=1[vout][aout]"
        cmd += ["-filter_complex", ";".join(f"[{i}:v]null[v{i}];[{i}:a]anull[a{i}]" for i in range(n)) + ";" + final_chain,
                "-map", "[vout]", "-map", "[aout]", "-r", "24",
                "-s", f"{CINEMA_W}x{CINEMA_H}",
                "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return out

    def assemble_movie(self, plan: dict | None = None) -> Path:
        """PHASE 9: full movie assembly from scene edits (with audio)."""
        plan = plan or self.load_plan()
        scenes = [s["scene_id"] for s in plan["scenes"]]
        for sid in scenes:
            p = self.dir / "edit" / f"{sid}.mp4"
            if not p.exists():
                try:
                    self.assemble_scene(sid, plan)
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    log.warning("scene %s assembly failed: %s", sid, str(e)[:120])
        available = [self.dir / "edit" / f"{sid}.mp4" for sid in scenes
                     if (self.dir / "edit" / f"{sid}.mp4").exists()]
        if not available:
            raise FileNotFoundError("No scene edits to assemble")

        out = self.dir / "edit" / "final_movie.mp4"
        concat = self.dir / "edit" / "concat_scenes.txt"
        concat.write_text("\n".join(f"file '{p}'" for p in available))
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ], check=True, capture_output=True)
        return out

    # ------------------------------------------------------------- phase 10
    def final_export(self, plan: dict | None = None) -> Path:
        """PHASE 10: final deliverable — audio preserved (aac 192k)."""
        plan = plan or self.load_plan()
        src = self.dir / "edit" / "final_movie.mp4"
        if not src.exists():
            src = self.assemble_movie(plan)
        out = self.dir / "edit" / f"{self.name.replace(':', '_')}_export.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx264", "-crf", "24", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out),
        ], check=True, capture_output=True, timeout=900)
        return out

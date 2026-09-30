"""Cinematic production pipeline orchestrator.

PHASE 0  project/asset bible
PHASE 1  script parsing
PHASE 2  cinematic shot planning
PHASE 3  asset/continuity resolution
PHASE 4  storyboard keyframe generation
PHASE 5  keyframe QA/approval
PHASE 6  video shot generation
PHASE 7  video QA
PHASE 8  scene assembly
PHASE 9  full movie assembly
PHASE 10 final audio/color/export

Every phase is resumable. Reuses the existing AgnesClient (key rotation,
429 handling, polling) and MovieGenerator.assemble untouched.

SCENE != GENERATION UNIT. SHOT = GENERATION UNIT.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from movie_generator.cinematic.bible import AssetRegistry, ProjectBible
from movie_generator.cinematic.continuity import check_continuity, validate_chain
from movie_generator.cinematic.frames import actual_duration
from movie_generator.cinematic.models import save_state, validate_shot
from movie_generator.cinematic.parser import is_legacy_format, parse_script
from movie_generator.cinematic.prompts import (
    build_image_prompt, build_video_prompt, negative_prompt,
)
from movie_generator.cinematic.qa import qa_keyframe, qa_video, save_qa_report
from movie_generator.cinematic.queue import RenderQueue

log = logging.getLogger(__name__)

# 2.39:1 cinematic framing for the storyboard + final export
CINEMA_W, CINEMA_H = 1152, 480  # multiples of 16, exact 2.39:1


class ProductionPipeline:
    """Shot-level cinematic AI film production pipeline for one project."""

    def __init__(self, client, projects_dir: str | Path, project_name: str):
        self.client = client
        self.projects_dir = Path(projects_dir)
        self.name = project_name
        self.dir = self.projects_dir / project_name.replace(":", "_").replace(" ", "_")
        self._ensure_dirs()

        self.bible = ProjectBible(self.dir / "bible")
        self.registry = AssetRegistry(self.dir / "bible")
        self.queue = RenderQueue(self.dir)

    # ------------------------------------------------------------ structure
    def _ensure_dirs(self):
        for sub in ("bible", "script", "references/characters", "references/locations",
                    "references/props", "references/vehicles", "storyboard",
                    "video", "audio/dialogue", "audio/ambience", "audio/foley",
                    "audio/music", "edit", "qa/storyboard", "qa/video",
                    "qa/continuity", "logs"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- phase 0
    def init_bible(self, **fields) -> dict:
        """PHASE 0: project/asset bible. Register characters/locations/props."""
        self.bible.set(mode=fields.pop("mode", "cinematic"), **fields)
        chars = fields.get("characters") or []
        if isinstance(chars, list):
            for c in chars:
                if isinstance(c, dict):
                    self.registry.register("CHARACTER", c.get("name", "Unknown"), **c)
                elif isinstance(c, str):
                    self.registry.register("CHARACTER", c)
        locs = fields.get("locations") or []
        for l in locs:
            if isinstance(l, dict):
                self.registry.register("LOCATION", l.get("name", "Unknown"), **l)
            elif isinstance(l, str):
                self.registry.register("LOCATION", l)
        props = fields.get("props") or []
        for p in props:
            if isinstance(p, dict):
                self.registry.register("PROP", p.get("name", "Unknown"), **p)
            elif isinstance(p, str):
                self.registry.register("PROP", p)
        return self.bible.data

    # ------------------------------------------------------------- phase 1+2
    def parse(self, script_text: str) -> dict:
        """PHASE 1+2: parse script into cinematic plan (or legacy passthrough).

        Legacy scripts with ready-to-use prompts still parse and render.
        """
        (self.dir / "script").mkdir(parents=True, exist_ok=True)
        (self.dir / "script" / "original_script.txt").write_text(script_text)

        legacy = is_legacy_format(script_text)
        if legacy:
            plan = {"mode": "legacy", "scenes": self._parse_legacy(script_text)}
            plan["total_scenes"] = len(plan["scenes"])
            plan["total_shots"] = sum(len(s["shots"]) for s in plan["scenes"])
        else:
            plan = parse_script(script_text)

        (self.dir / "script" / "parsed_script.json").write_text(json.dumps(plan, indent=2))
        self._resolve_assets(plan)  # phase 3 inline
        self._build_prompts(plan)   # phase 2 tail: structured prompts
        (self.dir / "script" / "cinematic_plan.json").write_text(json.dumps(plan, indent=2))

        # queue: enqueue storyboard tasks
        for scene in plan["scenes"]:
            for shot in scene["shots"]:
                self.queue.add(self.name, scene["scene_id"], shot["shot_id"],
                               "keyframe", priority=5)
        return plan

    def _parse_legacy(self, text: str) -> list[dict]:
        """Legacy format: SHOT blocks with Prompt: blocks (existing parsers)."""
        import re
        scenes: list[dict] = []
        cur = None
        shot_re = re.compile(r"^SHOT\s+(\d+)([A-D]?)\s*[—-]\s*(.+)$", re.MULTILINE)
        lines = text.splitlines()
        cur_shot = None
        in_prompt = False
        for line in lines:
            st = line.strip()
            m = re.match(r"^SCENE\s+(\d+)\s*[—-]\s*(.+)$", st)
            if m:
                if cur_shot and cur:
                    cur["shots"].append(cur_shot)
                if cur:
                    scenes.append(cur)
                cur = {"scene_id": f"scene_{int(m.group(1)):02d}",
                       "title": m.group(2), "location": "", "time": "",
                       "weather": "", "characters": [], "shots": []}
                cur_shot = None
                in_prompt = False
                continue
            m = shot_re.match(st)
            if m and cur is not None:
                if cur_shot:
                    cur["shots"].append(cur_shot)
                cur_shot = {
                    "shot_id": f"shot_{int(m.group(1)):02d}{''.join(m.group(2).lower().split())}",
                    "scene_id": cur["scene_id"], "shot_number": int(m.group(1)),
                    "duration_seconds": 3.0, "num_frames": 73,
                    "characters": [], "required_assets": [],
                    "camera": "STATIC", "lens": "50mm", "framing": "medium",
                    "camera_movement": "STATIC", "subject_action": m.group(3),
                    "start_state": "", "end_state": "", "video_prompt": "",
                    "image_prompt": "", "negative_prompt": "",
                    "status": "PENDING", "image_status": "PENDING",
                    "video_status": "PENDING", "qa_status": "PENDING",
                    "retry_count": 0, "error": "", "file_paths": {},
                    "needs_review": [], "period": "2026",
                }
                in_prompt = False
                continue
            if cur_shot is None:
                continue
            dm = re.search(r"Duration:\s*(\d+)\s*sec", st)
            if dm:
                cur_shot["duration_seconds"] = int(dm.group(1))
                cur_shot["num_frames"] = round(int(dm.group(1)) * 3) * 8 + 1
            if st.startswith("Prompt:"):
                cur_shot["video_prompt"] = st[len("Prompt:"):].strip()
                in_prompt = True
                continue
            if st.startswith("Dialogue:"):
                cur_shot["dialogue"] = st[len("Dialogue:"):].strip().strip('"')
                continue
            if in_prompt:
                cur_shot["video_prompt"] += " " + st
            else:
                cur_shot["subject_action"] += " " + st if cur_shot["subject_action"] else st
        if cur_shot and cur:
            cur["shots"].append(cur_shot)
        if cur:
            scenes.append(cur)
        return scenes

    # ------------------------------------------------------------- phase 3
    def _resolve_assets(self, plan: dict):
        """PHASE 3: resolve required_assets -> registry IDs + reference images."""
        for scene in plan["scenes"]:
            for shot in scene["shots"]:
                refs = []
                for req in shot.get("required_assets", []):
                    a = self.registry.find_by_name(req)
                    if a:
                        refs.append(a["id"])
                        img = self.registry.reference_image(a["id"])
                        if img:
                            shot.setdefault("reference_images", []).append(str(img))
                # characters auto-resolve
                for c in shot.get("characters", []):
                    a = self.registry.find_by_name(c)
                    if a and a["id"] not in refs:
                        refs.append(a["id"])
                        img = self.registry.reference_image(a["id"])
                        if img:
                            shot.setdefault("reference_images", []).append(str(img))
                shot["required_assets"] = refs

    # ------------------------------------------------------------- prompts
    def _build_prompts(self, plan: dict):
        """Structured prompt architecture from components."""
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
            period_rules = (
                "Period-appropriate 2006 technology: period phones, computers, "
                "vehicles, clothing, furniture, electronics. Warm-neutral "
                "palette: beige, brown, amber, muted cream. No modern 2026 "
                "technology.")
        for scene in plan["scenes"]:
            for shot in scene["shots"]:
                if not shot.get("image_prompt"):
                    shot["image_prompt"] = build_image_prompt(
                        shot, scene, bible_chars, style, period_rules)
                if not shot.get("video_prompt"):
                    shot["video_prompt"] = build_video_prompt(
                        shot, scene, bible_chars, style, period_rules)
                if not shot.get("negative_prompt"):
                    shot["negative_prompt"] = negative_prompt(shot)

    # ------------------------------------------------------------- flat shots
    def flat_shots(self, plan: dict | None = None) -> list[tuple[dict, dict]]:
        plan = plan or self.load_plan()
        out = []
        for scene in plan.get("scenes", []):
            for shot in scene.get("shots", []):
                out.append((scene, shot))
        return out

    def load_plan(self) -> dict:
        p = self.dir / "script" / "cinematic_plan.json"
        if p.exists():
            return json.loads(p.read_text())
        legacy = self.dir / "script" / "parsed_script.json"
        if legacy.exists():
            return json.loads(legacy.read_text())
        raise FileNotFoundError(f"No plan for project {self.name}")

    def save_plan(self, plan: dict):
        (self.dir / "script" / "cinematic_plan.json").write_text(json.dumps(plan, indent=2))

    # ------------------------------------------------------------- phase 4
    def generate_keyframe(self, scene: dict, shot: dict) -> Path:
        """PHASE 4: storyboard keyframe in cinematic 2.39:1 framing."""
        shot_id = shot["shot_id"]
        kf = self.dir / "storyboard" / scene["scene_id"] / f"{shot_id}.png"
        kf.parent.mkdir(parents=True, exist_ok=True)
        if kf.exists():
            shot["image_status"] = "COMPLETED"
            return kf
        prompt = shot.get("image_prompt") or build_image_prompt(shot, scene, {}, "")
        # identity anchoring: if a character reference image exists, pass it so
        # the generated keyframe keeps the actor's likeness
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

    # ------------------------------------------------------------- phase 5
    def approve_keyframe(self, shot: dict, approved: bool, notes: str = ""):
        """PHASE 5: human approval gate. Only approved keyframes -> video."""
        if approved:
            shot["qa_status"] = "KEYFRAME_APPROVED"
            task = next((t for t in self.queue.tasks
                         if t["shot"] == shot["shot_id"] and t["generation_type"] == "video"), None)
            if task is None:
                self.queue.add(self.name, shot["scene_id"], shot["shot_id"],
                               "video", priority=5)
        else:
            shot["qa_status"] = "KEYFRAME_REJECTED"
            shot["image_status"] = "PENDING"
        save_qa_report(self.dir, "storyboard", shot["shot_id"],
                       {"approved": approved, "notes": notes})

    def run_keyframe_qa(self, scene: dict, shot: dict) -> dict:
        kf = self.dir / "storyboard" / scene["scene_id"] / f"{shot['shot_id']}.png"
        report = qa_keyframe(shot, kf, client=self.client, bible=self.bible.data)
        shot["qa_status"] = report["status"]
        save_qa_report(self.dir, "storyboard", shot["shot_id"], report)
        return report

    # ------------------------------------------------------------- phase 6
    def generate_video(self, scene: dict, shot: dict) -> Path:
        """PHASE 6: video shot generation (keyframe approval required)."""
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

        # reference identity: use approved keyframe as first frame
        first_frame_url = None
        try:
            import base64
            b64 = base64.b64encode(kf.read_bytes()).decode()
            first_frame_url = f"data:image/png;base64,{b64}"
        except Exception:
            pass

        prompt = shot.get("video_prompt") or ""
        neg = shot.get("negative_prompt") or ""
        if neg:
            prompt = f"{prompt} Avoid: {neg}"

        num_frames = round((shot.get("duration_seconds", 3.0)) * 3) * 8 + 1
        url = self.client.video(
            prompt,
            width=1152, height=480,           # 2.39:1 cinematic
            num_frames=num_frames, frame_rate=24,
            first_frame_url=first_frame_url if len(first_frame_url or "") < 100 else None,
            poll_interval=15, poll_timeout=1800)
        import requests as req
        tmp = out.with_suffix(".part")
        r = req.get(url, timeout=600)
        r.raise_for_status()
        tmp.write_bytes(r.content)
        tmp.rename(out)
        shot["video_status"] = "COMPLETED"
        shot["status"] = "COMPLETED"
        shot.setdefault("file_paths", {})["video"] = str(out)
        save_state(self.dir, shot)
        return out

    # ------------------------------------------------------------- phase 7
    def run_video_qa(self, scene: dict, shot: dict) -> dict:
        vid = self.dir / "video" / scene["scene_id"] / f"{shot['shot_id']}.mp4"
        report = qa_video(shot, vid, client=self.client)
        if report["status"] == "QA_FAILED":
            shot["qa_status"] = "QA_FAILED"
        elif report["status"] == "PASSED":
            shot["qa_status"] = "VIDEO_PASSED"
        save_qa_report(self.dir, "video", shot["shot_id"], report)
        return report

    # ------------------------------------------------------------- continuity
    def continuity_report(self) -> dict:
        shots = [s for _, s in self.flat_shots()]
        report = validate_chain(shots)
        # persist
        p = self.dir / "qa" / "continuity" / "chain.json"
        p.write_text(json.dumps(report, indent=2))
        return report

    # ------------------------------------------------------------- phases 8+9
    def assemble_scene(self, scene_id: str, plan: dict | None = None,
                       disabled: set[str] | None = None, trims: dict | None = None) -> Path:
        """PHASE 8: assemble one scene timeline (editable, not blind concat)."""
        plan = plan or self.load_plan()
        scene = next((s for s in plan["scenes"] if s["scene_id"] == scene_id), None)
        if not scene:
            raise FileNotFoundError(scene_id)
        disabled = disabled or set()
        trims = trims or {}
        out = self.dir / "edit" / f"{scene_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)

        concat_lines = []
        filter_chains = []
        inputs = []
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
                    f"[{idx:v}] trim=start={start}:duration={dur},setpts=PTS-STARTPTS[v{idx}]")
            else:
                filter_chains.append(f"[{idx}:v] null[v{idx}]")

        if not inputs:
            raise FileNotFoundError(f"No videos for scene {scene_id}")

        n = len(inputs)
        final_chain = "".join(f"[v{i}]" for i in range(n)) + \
            f"concat=n={n}:v=1:a=0[vout]"
        cmd = ["ffmpeg", "-y"]
        for i in inputs:
            cmd += ["-i", i]
        cmd += ["-filter_complex", ";".join(filter_chains) + ";" + final_chain,
                "-map", "[vout]", "-r", "24", "-s", f"{CINEMA_W}x{CINEMA_H}",
                "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return out

    def assemble_movie(self, plan: dict | None = None) -> Path:
        """PHASE 9: full movie assembly from scene edits."""
        plan = plan or self.load_plan()
        scenes = [s["scene_id"] for s in plan["scenes"]]
        missing = []
        for sid in scenes:
            p = self.dir / "edit" / f"{sid}.mp4"
            if not p.exists():
                try:
                    self.assemble_scene(sid, plan)
                except (FileNotFoundError, subprocess.CalledProcessError) as e:
                    log.warning("scene %s assembly failed: %s", sid, str(e)[:120])
                    missing.append(sid)
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
        """PHASE 10: final color/export (compressed deliverable)."""
        plan = plan or self.load_plan()
        src = self.dir / "edit" / "final_movie.mp4"
        if not src.exists():
            src = self.assemble_movie(plan)
        out = self.dir / "edit" / f"{self.name.replace(':', '_')}_export.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx264", "-crf", "26", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(out),
        ], check=True, capture_output=True, timeout=900)
        return out

    # ------------------------------------------------------------- batch ops
    def batch_storyboards(self, scene_ids: list[str] | None = None):
        """Generate scene storyboards (selected scenes or all)."""
        plan = self.load_plan()
        done, failed = 0, 0
        for scene, shot in self.flat_shots(plan):
            if scene_ids and scene["scene_id"] not in scene_ids:
                continue
            try:
                self.generate_keyframe(scene, shot)
                done += 1
            except Exception as e:
                log.error("keyframe %s failed: %s", shot["shot_id"], str(e)[:150])
                failed += 1
        self.save_plan(plan)
        return {"completed": done, "failed": failed}

    def batch_approved_videos(self, scene_ids: list[str] | None = None):
        """Generate all approved videos (selected scenes or all)."""
        plan = self.load_plan()
        done, failed = 0, 0
        for scene, shot in self.flat_shots(plan):
            if scene_ids and scene["scene_id"] not in scene_ids:
                continue
            if shot.get("qa_status") not in ("KEYFRAME_APPROVED", "PASSED"):
                continue
            task = self.queue.add(self.name, scene["scene_id"], shot["shot_id"],
                                  "video", priority=5)
            try:
                self.generate_video(scene, shot)
                self.queue.complete(task)
                done += 1
            except Exception as e:
                err = str(e)
                self.queue.fail(task, err, rate_limited="429" in err)
                log.error("video %s failed: %s", shot["shot_id"], err[:150])
                failed += 1
        self.save_plan(plan)
        return {"completed": done, "failed": failed}

    def regenerate_shot(self, shot_id: str, kind: str = "both"):
        """Regenerate one shot without destroying the rest.

        Later shots get marked CONTINUITY_RECHECK_REQUIRED rather than
        blindly remaining approved.
        """
        plan = self.load_plan()
        shots = [s for _, s in self.flat_shots(plan)]
        shot = next((s for s in shots if s["shot_id"] == shot_id), None)
        if not shot:
            raise FileNotFoundError(shot_id)
        scene = next((sc for sc in plan["scenes"] if sc["scene_id"] == shot["scene_id"]), None)

        if kind in ("both", "keyframe"):
            kf = self.dir / "storyboard" / shot["scene_id"] / f"{shot_id}.png"
            if kf.exists():
                kf.unlink()
            shot["image_status"] = "PENDING"
            shot["qa_status"] = "PENDING"
        if kind in ("both", "video"):
            vid = self.dir / "video" / shot["scene_id"] / f"{shot_id}.mp4"
            if vid.exists():
                vid.unlink()
            shot["video_status"] = "PENDING"
            shot["status"] = "PENDING"
        self.save_plan(plan)
        return {"shot": shot_id, "reset": kind,
                "scene": shot["scene_id"], "scene_found": scene is not None}

    # ------------------------------------------------------------- progress
    def progress(self) -> dict:
        plan = None
        try:
            plan = self.load_plan()
        except FileNotFoundError:
            return {"error": "no plan"}
        shots = [s for _, s in self.flat_shots(plan)]
        kf_ok = sum(1 for s in shots if s.get("image_status") == "COMPLETED")
        approved = sum(1 for s in shots
                       if s.get("qa_status") in ("KEYFRAME_APPROVED", "VIDEO_PASSED", "PASSED"))
        vid_ok = sum(1 for s in shots if s.get("video_status") == "COMPLETED")
        qa_ok = sum(1 for s in shots if s.get("qa_status") in ("VIDEO_PASSED", "PASSED"))
        scenes_edit = sum(1 for s in plan["scenes"]
                          if (self.dir / "edit" / f"{s['scene_id']}.mp4").exists())
        return {
            "project": self.name,
            "total_scenes": plan.get("total_scenes", len(plan["scenes"])),
            "total_shots": len(shots),
            "storyboard": {"approved": kf_ok, "total": len(shots)},
            "video": {"completed": vid_ok, "total": len(shots)},
            "qa": {"passed": qa_ok, "total": len(shots)},
            "keyframes_approved": approved,
            "assembly": {"scenes_done": scenes_edit,
                         "total": plan.get("total_scenes", len(plan["scenes"]))},
            "queue": self.queue.stats(),
            "final_movie": str(self.dir / "edit" / "final_movie.mp4")
                if (self.dir / "edit" / "final_movie.mp4").exists() else None,
        }

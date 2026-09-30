"""Cinematic script parser: upgrade of parse_script.py.

Parses the explicit cinematic production format:

    SCENE 01
    TITLE: 2:07 AM
    LOCATION: / TIME: / WEATHER: / SCENE_DURATION:
    SHOT 01-01
    DURATION: / LENS: / ... / START_STATE: / END_STATE: / IMAGE_PROMPT: ...

Backward compatible with the legacy format (SHOT XX — Title blocks with
ready-to-use Prompt: blocks). Missing critical fields are marked
NEEDS_REVIEW, never hallucinated.
"""
from __future__ import annotations

import json
import re

from movie_generator.cinematic.frames import clamp_duration_for_level, calculate_num_frames
from movie_generator.cinematic.models import default_shot

FIELD_KEYS = [
    "DURATION", "LENS", "FRAMING", "CAMERA", "CHARACTERS", "ACTION",
    "PERFORMANCE", "START_STATE", "END_STATE", "DIALOGUE",
    "DIALOGUE_SPEAKER", "SFX", "AMBIENCE", "FOLEY", "MUSIC",
    "TRANSITION", "COMPLEXITY", "GENERATION_LEVEL", "REFERENCE_ASSETS",
    "IMAGE_PROMPT", "VIDEO_PROMPT", "NEGATIVE_PROMPT", "PERIOD",
    "WEATHER", "EXPRESSION", "LOCATION", "TIME", "SCENE_DURATION",
    "SCENE_GOAL", "EMOTIONAL_GOAL", "BLOCKING", "LIGHTING", "COLOR",
    "ENVIRONMENT",
]

SCENE_RE = re.compile(r"^SCENE\s+(\d+)", re.IGNORECASE)
SHOT_RE = re.compile(r"^SHOT\s+(\d+)(?:-(\d+))?", re.IGNORECASE)
FIELD_RE = re.compile(r"^([A-Z_]+):\s*(.*)$")


class _CinematicParser:
    def __init__(self):
        self.scenes: list[dict] = []
        self.cur_scene: dict | None = None
        self.cur_shot: dict | None = None
        self.shot_counter = 0

    # ------------------------------------------------------------- helpers
    def flush_shot(self):
        if self.cur_shot and self.scenes:
            self.scenes[-1]["shots"].append(self.cur_shot)
        self.cur_shot = None

    def flush_scene(self):
        self.flush_shot()
        self.cur_scene = None

    def _start_scene(self, num: int):
        self.flush_scene()
        self.cur_scene = {
            "scene_id": f"scene_{num:02d}",
            "scene_number": num,
            "title": "",
            "location": "", "time": "", "weather": "",
            "scene_duration": 0, "characters": [], "props": [],
            "scene_goal": "", "emotional_goal": "",
            "continuity_in": "", "continuity_out": "",
            "shots": [],
        }
        self.scenes.append(self.cur_scene)

    def _start_shot(self, scene_num: int, shot_num: int | None):
        if self.cur_scene is None:
            self._start_scene(scene_num)
        self.flush_shot()
        self.shot_counter += 1
        if shot_num is None:
            existing = [s["shot_number"] for s in self.cur_scene["shots"]]
            shot_num = (max(existing) + 1) if existing else 1
        shot_id = f"shot_{scene_num:02d}-{shot_num:02d}"
        self.cur_shot = default_shot(shot_id, self.cur_scene["scene_id"], shot_num)

    # ------------------------------------------------------------- field set
    def _set_field(self, key: str, value: str):
        s = self.cur_shot
        sc = self.cur_scene
        v = value.strip()

        if key == "TITLE" and sc is not None and s is None:
            sc["title"] = v
        elif key in ("LOCATION", "TIME", "WEATHER", "SCENE_DURATION",
                     "SCENE_GOAL", "EMOTIONAL_GOAL") and s is None:
            if key == "SCENE_DURATION":
                num = re.search(r"(\d+)", v)
                sc["scene_duration"] = int(num.group(1)) if num else 0
            else:
                sc[key.lower()] = v
        elif s is None:
            return  # unknown scene-level line, ignore

        if key == "DURATION":
            num = re.search(r"(\d+(?:\.\d+)?)", v)
            if num:
                s["duration_seconds"] = float(num.group(1))
        elif key == "LENS":
            mm = re.search(r"(\d+)\s*mm", v, re.IGNORECASE)
            if mm:
                s["lens"] = f"{mm.group(1)}mm"
            else:
                s["needs_review"].append("lens")
        elif key == "FRAMING":
            s["framing"] = v.lower()
        elif key == "CAMERA":
            s["camera"] = v.upper().replace(" ", "_")
            s["camera_movement"] = v.upper().replace(" ", "_")
        elif key == "CHARACTERS":
            s["characters"] = [c.strip() for c in re.split(r"[;,/]", v) if c.strip()]
            if sc and v and v not in sc["characters"]:
                sc["characters"].append(v)
        elif key == "ACTION":
            s["subject_action"] = v
        elif key == "PERFORMANCE":
            s["performance"] = v
        elif key == "EXPRESSION":
            s["expression"] = v
        elif key == "START_STATE":
            s["start_state"] = v
        elif key == "END_STATE":
            s["end_state"] = v
            s["continuity_to"] = v
        elif key == "DIALOGUE":
            s["dialogue"] = v.strip('"')
        elif key == "DIALOGUE_SPEAKER":
            s["dialogue_speaker"] = v
        elif key in ("SFX", "AMBIENCE", "FOLEY", "MUSIC"):
            s[key.lower()] = v
        elif key == "TRANSITION":
            s["transition_out"] = v.lower()
        elif key == "COMPLEXITY":
            num = re.search(r"(\d+)", v)
            if num:
                s["complexity_level"] = int(num.group(1))
        elif key == "GENERATION_LEVEL":
            num = re.search(r"(\d+)", v)
            if num:
                s["generation_level"] = int(num.group(1))
        elif key == "REFERENCE_ASSETS":
            s["required_assets"] = [a.strip() for a in re.split(r"[;,]", v) if a.strip()]
        elif key == "IMAGE_PROMPT":
            s["image_prompt"] = v
        elif key == "VIDEO_PROMPT":
            s["video_prompt"] = v
        elif key == "NEGATIVE_PROMPT":
            s["negative_prompt"] = v
        elif key == "PERIOD":
            s["period"] = v
        elif key == "BLOCKING":
            s["blocking"] = v
        elif key in ("LIGHTING", "COLOR", "ENVIRONMENT"):
            s[key.lower()] = v

    # ------------------------------------------------------------- main parse
    def parse(self, text: str) -> dict:
        lines = text.splitlines()
        current_field: str | None = None

        for raw in lines:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                current_field = None
                continue

            m = SCENE_RE.match(stripped)
            if m and not stripped.startswith(("SHOT", "SHOT-")):
                num = int(m.group(1))
                # only start a new scene if this line is a bare SCENE header
                # (SHOT lines like "SHOT 15-01" also start with digits but
                # don't match SCENE)
                if re.match(r"^SCENE\s+\d+\s*$", stripped) or \
                   not re.match(r"^SHOT\s", stripped):
                    self._start_scene(num)
                    current_field = None
                    continue

            m = SHOT_RE.match(stripped)
            if m and self.cur_scene is not None:
                scene_num = self.cur_scene["scene_number"]
                shot_num = int(m.group(2)) if m.group(2) else None
                self._start_shot(scene_num, shot_num)
                current_field = None
                continue

            m = FIELD_RE.match(stripped)
            if m:
                current_field = m.group(1)
                self._set_field(current_field, m.group(2))
                continue

            # continuation of a multi-line field
            if current_field and self.cur_shot is not None:
                self._set_field(current_field, stripped)

        self.flush_scene()
        return self._finalize()

    # ------------------------------------------------------------- finalize
    def _finalize(self) -> dict:
        total_shots = 0
        for sc in self.scenes:
            for s in sc["shots"]:
                # clamp duration to generation level bounds
                lvl = s.get("generation_level", 2)
                s["duration_seconds"] = clamp_duration_for_level(
                    s.get("duration_seconds", 3.0), lvl)
                s["num_frames"] = calculate_num_frames(s["duration_seconds"])
                if not s.get("start_state"):
                    s["needs_review"].append("start_state")
                if not s.get("end_state"):
                    s["needs_review"].append("end_state")
                if not s.get("subject_action"):
                    s["needs_review"].append("subject_action")
                if not s.get("location_id") or s["location_id"] == "NEEDS_REVIEW":
                    # derive from scene location when safe
                    if sc.get("location"):
                        s["location_id"] = f"LOC-{sc['scene_id'].upper()}"
                    else:
                        s["needs_review"].append("location_id")
                if not s.get("video_prompt"):
                    s["needs_review"].append("video_prompt")
            total_shots += len(sc["shots"])

        return {
            "mode": "cinematic",
            "total_scenes": len(self.scenes),
            "total_shots": total_shots,
            "scenes": self.scenes,
        }


def parse_script(text: str) -> dict:
    """Parse a cinematic production script into a structured plan."""
    parser = _CinematicParser()
    return parser.parse(text)


def is_legacy_format(text: str) -> bool:
    """True if the script uses the legacy format (ready-to-use prompts)."""
    return bool(re.search(r"^Prompt:", text, re.MULTILINE)) and \
        not bool(re.search(r"^VIDEO_PROMPT:", text, re.MULTILINE))

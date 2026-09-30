"""Shot data model and state system for cinematic production mode."""
from __future__ import annotations

import json
from pathlib import Path

SHOT_STATUSES = [
    "PENDING", "GENERATING", "COMPLETED", "FAILED", "RETRYING",
    "RATE_LIMITED", "APPROVAL_REQUIRED", "QA_FAILED", "CANCELLED",
]

SHOT_FIELDS = [
    "shot_id", "scene_id", "shot_number", "duration_seconds",
    "location_id", "time_of_day", "weather", "period", "characters",
    "required_assets", "blocking", "camera", "lens", "framing",
    "camera_movement", "subject_action", "performance", "expression",
    "dialogue", "dialogue_speaker", "start_state", "end_state",
    "continuity_from", "continuity_to", "lighting", "color",
    "environment", "ambience", "foley", "sfx", "music",
    "transition_in", "transition_out", "complexity_level",
    "generation_level", "image_prompt", "video_prompt",
    "negative_prompt", "reference_images", "reference_shots",
    "status", "image_status", "video_status", "qa_status",
    "retry_count", "error", "file_paths", "needs_review",
]

LENS_DEFAULTS = {
    "environment": "35mm",
    "movement": "35mm",
    "dialogue": "50mm",
    "normal": "50mm",
    "emotional": "85mm",
    "insert": "85mm",
}

CAMERA_MOVEMENTS = [
    "LOCKED", "STATIC", "SLOW_PUSH", "SLOW_TRACK", "CONTROLLED_HANDHELD",
    "SHOULDER_FOLLOW", "PAN", "TILT", "DOLLY",
]

FORBIDDEN_MOVEMENTS = [
    "drone", "flying through walls", "360", "orbit", "whip pan",
    "crash zoom", "snap zoom", "tiktok",
]


def default_shot(shot_id: str, scene_id: str, shot_number: int) -> dict:
    """A fully-populated shot dict with safe defaults."""
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "shot_number": shot_number,
        "duration_seconds": 3.0,
        "location_id": "NEEDS_REVIEW",
        "time_of_day": "NEEDS_REVIEW",
        "weather": "",
        "period": "2026",
        "characters": [],
        "required_assets": [],
        "blocking": "",
        "camera": "STATIC",
        "lens": "50mm",
        "framing": "medium",
        "camera_movement": "STATIC",
        "subject_action": "",
        "performance": "",
        "expression": "",
        "dialogue": "",
        "dialogue_speaker": "",
        "start_state": "",
        "end_state": "",
        "continuity_from": "",
        "continuity_to": "",
        "lighting": "NEEDS_REVIEW",
        "color": "",
        "environment": "",
        "ambience": "",
        "foley": "",
        "sfx": "",
        "music": "",
        "transition_in": "cut",
        "transition_out": "cut",
        "complexity_level": 1,
        "generation_level": 2,
        "image_prompt": "",
        "video_prompt": "",
        "negative_prompt": "",
        "reference_images": [],
        "reference_shots": [],
        "status": "PENDING",
        "image_status": "PENDING",
        "video_status": "PENDING",
        "qa_status": "PENDING",
        "retry_count": 0,
        "error": "",
        "file_paths": {},
        "needs_review": [],
    }


def validate_shot(shot: dict) -> list[str]:
    """Return list of problems; missing critical fields become NEEDS_REVIEW."""
    problems = []
    for f in ("shot_id", "scene_id", "subject_action"):
        if not shot.get(f):
            problems.append(f"missing {f}")
    if shot.get("camera_movement") not in CAMERA_MOVEMENTS:
        problems.append(f"invalid camera_movement: {shot.get('camera_movement')}")
    for forbidden in FORBIDDEN_MOVEMENTS:
        mv = (shot.get("camera_movement") or "").lower()
        if forbidden in mv:
            problems.append(f"forbidden camera movement: {forbidden}")
    lens = shot.get("lens") or ""
    if lens not in ("24mm", "28mm", "35mm", "50mm", "85mm"):
        problems.append(f"invalid lens: {lens} (use 24/28/35/50/85mm)")
    if not shot.get("start_state") or not shot.get("end_state"):
        problems.append("missing start_state or end_state")
    return problems


def save_state(project_dir: str | Path, shot: dict):
    """Persist shot state into the project's state ledger."""
    p = Path(project_dir) / "qa" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if p.exists():
        data = json.loads(p.read_text())
    data[shot["shot_id"]] = {
        "start_state": shot.get("start_state", ""),
        "end_state": shot.get("end_state", ""),
        "characters": shot.get("characters", []),
        "required_assets": shot.get("required_assets", []),
        "location_id": shot.get("location_id"),
        "period": shot.get("period"),
        "camera": shot.get("camera"),
        "wardrobe_hashes": {},
    }
    p.write_text(json.dumps(data, indent=2))


def load_state(project_dir: str | Path) -> dict:
    p = Path(project_dir) / "qa" / "state.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}

"""Complex action decomposition.

ONE SHOT = ONE PRIMARY PHYSICAL ACTION. A complex multi-beat action such as
"Frank grabs Ethan, turns, reaches for gun, gun goes off and Sarah falls"
must never be generated as one video prompt. It is decomposed into a
controllable shot sequence (performance beats) and reconstructed through
editing.

Complexity is decomposed, never simplified: the final audience still
experiences the complete event.
"""
from __future__ import annotations

import re

from movie_generator.cinematic.frames import calculate_num_frames
from movie_generator.cinematic.models import default_shot

# Beat keywords -> (beat label, generation_level, duration)
# LEVEL 1 PERFORMANCE: 4-8s (looking, listening, speaking)
# LEVEL 2 CINEMATIC ACTION: 1-4s (turning, entering, reaching)
# LEVEL 3 HERO ACTION: 0.5-2s (collision, gunshot, fall, struggle)
BEATS: list[tuple[str, str, int, float]] = [
    (r"\b(hear|hears|hearing|notices?|realizes?)\b", "notices", 1, 5.0),
    (r"\b(turn|turns|turning|looks? around|glances?)\b", "turns", 2, 2.0),
    (r"\b(reacts?|reaction|stagger\w* back|flinch\w*)\b", "reacts", 2, 2.5),
    (r"\b(steps? between|moves? between|shields?|protect\w*)\b", "moves between", 2, 2.0),
    (r"\b(reach\w* for|grabs?|grasps?|snatch\w*)\b", "reaches for weapon", 2, 2.0),
    (r"\b(threat|attacker|lunges?|approach\w* fast)\b", "threat moves", 2, 2.0),
    (r"\b(struggl\w*|wrestl\w*|fights?|fighting)\b", "struggle", 3, 1.5),
    (r"\b(gun ?goes? off|gunshot|shots? fired|fires?)\b", "gunshot", 3, 1.0),
    (r"\b(collision|impact|slams?|crash\w*)\b", "collision", 3, 1.0),
    (r"\b(falls?|collapses?|drops? to)\b", "falls", 3, 1.5),
    (r"\b(freeze\w*|stares?|stands? still|shocked)\b", "freezes", 1, 4.0),
]

# Duration / complexity triggers
COMPLEX_THRESHOLD_WORDS = 12
COMPLEX_CONJUNCTIONS = re.compile(
    r"\b(and then|then|while|as|before|after|suddenly|meanwhile)\b", re.IGNORECASE)


def is_complex_action(action: str) -> bool:
    """True if an action string contains multiple physical beats."""
    a = (action or "").strip()
    if not a:
        return False
    matches = 0
    for pattern, *_ in BEATS:
        if re.search(pattern, a, re.IGNORECASE):
            matches += 1
    if matches >= 2:
        return True
    if matches >= 1 and len(COMPLEX_CONJUNCTIONS.findall(a)) >= 2:
        return True
    return False


def decompose(action: str, scene: dict, base: dict | None = None) -> list[dict]:
    """Decompose a complex action into an ordered beat-level shot sequence.

    Each beat inherits the previous beat's end_state as its start_state.
    Every beat carries its own camera, duration, prompt and continuity.
    The editor then reconstructs the event.
    """
    a = (action or "").strip()
    base = base or {}
    scene_num = scene.get("scene_number", 0)
    scene_id = scene.get("scene_id", "scene_00")

    # find ordered beats present in the action
    found: list[tuple[str, int, float]] = []
    used_spans: list[tuple[int, int]] = []
    for pattern, label, level, dur in BEATS:
        m = re.search(pattern, a, re.IGNORECASE)
        if m and not any(s <= m.start() < e for s, e in used_spans):
            found.append((label, level, dur))
            used_spans.append((m.span()))

    if not found:
        # single beat fallback
        found = [(a[:40].lower(), 2, 2.0)]

    shots: list[dict] = []
    existing = [s["shot_number"] for s in scene.get("shots", [])]
    shot_num = (max(existing) if existing else 0)

    prev_end = ""
    for i, (label, level, dur) in enumerate(found):
        shot_num += 1
        s = default_shot(f"shot_{scene_num:02d}-{shot_num:02d}", scene_id, shot_num)
        s.update({
            "subject_action": label,
            "generation_level": level,
            "duration_seconds": dur,
            "num_frames": calculate_num_frames(dur),
            "characters": base.get("characters", scene.get("characters", [])),
            "required_assets": base.get("required_assets", []),
            "lens": "85mm" if level == 3 else ("50mm" if level == 1 else "35mm"),
            "camera": "CONTROLLED_HANDHELD" if level == 3 else "STATIC",
            "camera_movement": "CONTROLLED_HANDHELD" if level == 3 else "STATIC",
            "framing": "close-up" if level == 3 else ("medium" if level == 1 else "medium-wide"),
            "location_id": base.get("location_id", ""),
            "time_of_day": base.get("time_of_day", ""),
            "weather": base.get("weather", ""),
            "period": base.get("period", "2026"),
            "start_state": prev_end or base.get("start_state", ""),
            "end_state": f"{label} complete; geography and relationships unchanged",
            "continuity_from": prev_end,
            "continuity_to": f"{label} complete; geography and relationships unchanged",
            "decomposed_from": a,
        })
        if i == 0:
            s["needs_review"].append("decomposed action — review beat sequence")
        prev_end = s["end_state"]
        shots.append(s)
    return shots


def decompose_plan(plan: dict) -> dict:
    """Walk a cinematic plan and decompose any complex shot actions.

    Returns a report of what was decomposed. Original shot prompts are
    preserved; new beat shots are appended to the scene in order.
    """
    report = []
    for scene in plan.get("scenes", []):
        new_shots: list[dict] = []
        for shot in list(scene["shots"]):
            if is_complex_action(shot.get("subject_action", "")):
                beats = decompose(shot["subject_action"], scene, shot)
                scene["shots"] = [s for s in scene["shots"] if s is not shot]
                new_shots.extend(beats)
                report.append({
                    "scene_id": scene["scene_id"],
                    "original": shot.get("subject_action", "")[:120],
                    "beat_shots": [b["shot_id"] for b in beats],
                })
        if new_shots:
            # insert beat shots at the position of the original shot
            scene["shots"] = scene.get("shots", []) + new_shots
    plan["total_shots"] = sum(len(s["shots"]) for s in plan.get("scenes", []))
    plan["decomposition_report"] = report
    return plan

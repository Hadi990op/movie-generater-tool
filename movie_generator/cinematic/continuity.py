"""Continuity engine: validates shot N start_state against shot N-1 end_state."""
from __future__ import annotations

from movie_generator.cinematic.models import load_state

MISMATCH_FLAGS = [
    "POSITION_MISMATCH", "WARDROBE_MISMATCH", "PROP_MISMATCH",
    "FACING_DIRECTION_MISMATCH", "LIGHTING_MISMATCH",
    "LOCATION_MISMATCH", "CHARACTER_IDENTITY_MISMATCH",
    "TIME_PERIOD_MISMATCH",
]


def _keyword_overlap(text_a: str, text_b: str) -> list[str]:
    """Words appearing in both texts (naive but useful heuristic)."""
    stop = {"the", "a", "an", "is", "in", "at", "of", "and", "to", "on",
            "with", "her", "his", "its", "from", "by", "for", "near",
            "behind", "front", "side", "still", "remains", "remains."}
    wa = {w.strip(".,;:").lower() for w in text_a.split()} - stop
    wb = {w.strip(".,;:").lower() for w in text_b.split()} - stop
    return sorted(wa & wb)


def check_continuity(prev_shot: dict, next_shot: dict) -> dict:
    """Compare next shot's start_state with prev shot's end_state.

    Returns {"flags": [...], "notes": str, "severity": "ok"|"warning"}.
    Warnings do NOT block generation; they surface in QA/UI.
    """
    flags = []
    prev_end = (prev_shot.get("end_state") or "").lower()
    next_start = (next_shot.get("start_state") or "").lower()

    if not prev_end or not next_start:
        return {"flags": ["INCOMPLETE_STATE"], "severity": "warning",
                "notes": "missing end_state or start_state for comparison"}

    # location must match unless intentionally scripted transition
    if (prev_shot.get("location_id") != next_shot.get("location_id")
            and next_shot.get("transition_in", "cut") == "cut"):
        flags.append("LOCATION_MISMATCH")

    # period must match
    if prev_shot.get("period") != next_shot.get("period"):
        flags.append("TIME_PERIOD_MISMATCH")

    # characters present in next but not established in prev scene context
    prev_chars = set(prev_shot.get("characters") or [])
    next_chars = set(next_shot.get("characters") or [])
    if next_chars - prev_chars and next_shot.get("transition_in", "cut") == "cut":
        flags.append("CHARACTER_IDENTITY_MISMATCH")

    # wardrobe: if wardrobe text present in both and no overlap
    overlap = _keyword_overlap(prev_end, next_start)
    if not overlap:
        flags.append("POSITION_MISMATCH")

    return {
        "flags": flags,
        "overlap": overlap,
        "severity": "warning" if flags else "ok",
        "notes": "; ".join(flags) if flags else "continuity consistent",
    }


def validate_chain(shots: list[dict]) -> dict:
    """Validate a full ordered shot chain; returns per-shot continuity report."""
    out = {}
    for i in range(1, len(shots)):
        prev, nxt = shots[i - 1], shots[i]
        out[nxt["shot_id"]] = check_continuity(prev, nxt)
    return out


def mark_recheck(project_dir: str | Path, regenerated_shot_id: str, shots: list[dict]):
    """After regenerating a shot, mark later shots CONTINUITY_RECHECK_REQUIRED.

    Shots before the regenerated one stay approved; later ones get flagged
    rather than blindly remaining approved.
    """
    from movie_generator.cinematic.models import save_state
    idx = next((i for i, s in enumerate(shots) if s["shot_id"] == regenerated_shot_id), None)
    if idx is None:
        return
    for s in shots[idx + 1:]:
        s["qa_status"] = "CONTINUITY_RECHECK_REQUIRED"
        save_state(project_dir, s)

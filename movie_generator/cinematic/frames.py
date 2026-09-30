"""Centralized duration/frame handling for the Agnes video API.

Agnes rule: num_frames must equal 8*n + 1 for integer n >= 0.
This is the ONLY place frame math lives — never hardcode frame values.
"""
from __future__ import annotations


def calculate_num_frames(duration_seconds: float, fps: int = 24) -> int:
    """Convert a target duration to the nearest valid Agnes frame count.

    Agnes requires num_frames = 8*n + 1 (e.g. 1, 9, 17, 25, 33, ...).
    We pick the n whose resulting duration is closest to the target,
    clamped to the Agnes minimum of 1 frame.

    Example: 3 sec @ 24fps -> 73 frames (~3.04 s).
    """
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be > 0")
    target_frames = duration_seconds * fps
    n = round((target_frames - 1) / 8)
    n = max(n, 0)
    return 8 * n + 1


def actual_duration(num_frames: int, fps: int = 24) -> float:
    """Actual duration of a valid frame count."""
    return num_frames / fps


def generation_level_bounds(level: int) -> tuple[float, float]:
    """(min, max) duration in seconds per generation level.

    LEVEL 1 PERFORMANCE: 4-8s
    LEVEL 2 CINEMATIC ACTION: 1-4s
    LEVEL 3 HERO ACTION: 0.5-2s
    """
    return {1: (4.0, 8.0), 2: (1.0, 4.0), 3: (0.5, 2.0)}.get(level, (1.0, 8.0))


def clamp_duration_for_level(duration_seconds: float, level: int) -> float:
    lo, hi = generation_level_bounds(level)
    return min(max(duration_seconds, lo), hi)

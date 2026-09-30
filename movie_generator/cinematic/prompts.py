"""Prompt architecture: structured component assembly, never chaotic prose.

IMAGE_PROMPT  = IDENTITY + LOCATION + TIME + WARDROBE + BLOCKING + CAMERA
                + LENS + LIGHTING + ENVIRONMENT + PERFORMANCE + STYLE + CONTINUITY
VIDEO_PROMPT  = REFERENCE IDENTITY + START STATE + ONE PRIMARY ACTION
                + PERFORMANCE + CAMERA MOVEMENT + ENVIRONMENT MOVEMENT
                + END STATE + CONTINUITY
NEGATIVE      = canonical anti-AI-look / anti-drift constraint list
"""
from __future__ import annotations

from movie_generator.cinematic.models import LENS_DEFAULTS

MOVEMENT_PROSE = {
    "LOCKED": "camera completely locked off",
    "STATIC": "camera static and steady",
    "SLOW_PUSH": "very slow controlled push-in toward the subject",
    "SLOW_TRACK": "slow lateral tracking movement",
    "CONTROLLED_HANDHELD": "controlled handheld camera with subtle natural movement",
    "SHOULDER_FOLLOW": "shoulder-mounted camera following the subject closely",
    "PAN": "slow motivated pan",
    "TILT": "slow motivated tilt",
    "DOLLY": "smooth dolly movement",
}

DEFAULT_NEGATIVE_PROMPT = (
    "identity drift, face morphing, face changing, age change, hair change, "
    "wardrobe change, different person, extra fingers, missing fingers, "
    "duplicate objects, floating objects, rubber limbs, unnatural walking, "
    "weightless movement, background morphing, background changing, "
    "lighting inconsistency, impossible shadows, eyeline errors, "
    "camera physics errors, camera flying through walls, 360 degree spin, "
    "drone shot, CGI look, cartoon look, 3D animation, plastic skin, "
    "beauty filter, beauty-filtered skin, airbrushed, futuristic elements, "
    "cyberpunk, neon, holograms, holographic UI, HUD, excessive lens flare, "
    "over-stylization, videogame rendering, teal-orange blockbuster grade, "
    "glowing edges, fake volumetric lighting, text, watermark, subtitles"
)


def _identity_text(characters: list[str], character_bible: dict) -> str:
    parts = []
    for name in characters:
        entry = character_bible.get(name) or _find_char(name, character_bible)
        if entry:
            parts.append(entry.get("locked_look") or entry.get("face_description", ""))
        else:
            parts.append(f"{name} (character identity per production bible)")
    return " ".join(parts)


def _find_char(name: str, bible: dict) -> dict | None:
    name_l = name.lower()
    for k, v in bible.items():
        if k.lower() == name_l or name_l in k.lower() or k.lower() in name_l:
            return v
    return None


def build_image_prompt(shot: dict, scene: dict | None, bible: dict,
                       visual_style: str, period_rules: str = "") -> str:
    """Structured image prompt assembly for the keyframe."""
    components = []

    ident = _identity_text(shot.get("characters", []), bible)
    if ident:
        components.append(ident)

    loc = (shot.get("location_id") or "").replace("NEEDS_REVIEW", "")
    scene_loc = (scene or {}).get("location", "")
    if scene_loc:
        components.append(f"Setting: {scene_loc}")
    elif loc:
        components.append(f"Setting: {loc}")

    tod = shot.get("time_of_day") or (scene or {}).get("time", "")
    if tod and tod != "NEEDS_REVIEW":
        components.append(f"Time of day: {tod}")

    weather = shot.get("weather") or (scene or {}).get("weather", "")
    if weather:
        components.append(f"Weather: {weather}")

    if shot.get("blocking"):
        components.append(f"Blocking: {shot['blocking']}")

    lens = shot.get("lens") or LENS_DEFAULTS.get(shot.get("framing", ""), "50mm")
    components.append(f"{lens} cinematic lens, {shot.get('framing', 'medium')} framing")

    movement = MOVEMENT_PROSE.get(shot.get("camera_movement", "STATIC"),
                                  MOVEMENT_PROSE["STATIC"])
    components.append(movement)

    lighting = shot.get("lighting") or ""
    if lighting and lighting != "NEEDS_REVIEW":
        components.append(f"Lighting: {lighting}")

    env = shot.get("environment") or ""
    if env:
        components.append(f"Environment detail: {env}")

    perf = shot.get("performance") or shot.get("expression") or ""
    if perf:
        components.append(f"Performance: {perf}")

    components.append(visual_style)

    if period_rules:
        components.append(period_rules)

    cont = shot.get("continuity_from") or ""
    if cont:
        components.append(f"Continuity from previous shot: {cont}")

    return ". ".join(c.rstrip(".") for c in components if c) + "."


def build_video_prompt(shot: dict, scene: dict | None, bible: dict,
                       visual_style: str, period_rules: str = "") -> str:
    """Structured video prompt: START STATE + ONE PRIMARY ACTION + END STATE.

    If the script already carries a ready VIDEO_PROMPT, use it and append
    structured continuity + style tails.
    """
    ready = (shot.get("video_prompt") or "").strip()
    if ready:
        tail = f" {visual_style}"
        if period_rules:
            tail += f" {period_rules}"
        cont = shot.get("continuity_from") or ""
        if cont:
            tail += f" Continuity from previous shot: {cont}"
        return ready + "." + tail

    components = []

    ident = _identity_text(shot.get("characters", []), bible)
    if ident:
        components.append(f"Characters: {ident}")

    start = shot.get("start_state") or ""
    if start:
        components.append(f"Start state: {start}")

    action = shot.get("subject_action") or ""
    if action:
        components.append(f"One primary action: {action}")

    perf = shot.get("performance") or ""
    if perf:
        components.append(f"Performance: {perf}")

    movement = MOVEMENT_PROSE.get(shot.get("camera_movement", "STATIC"),
                                  MOVEMENT_PROSE["STATIC"])
    lens = shot.get("lens") or "50mm"
    components.append(f"{movement}, {lens} lens, {shot.get('framing', 'medium')} framing")

    env = shot.get("environment") or (scene or {}).get("location", "")
    if env:
        components.append(f"Environment: {env}")

    end = shot.get("end_state") or ""
    if end:
        components.append(f"End state: {end}")

    components.append(visual_style)

    if period_rules:
        components.append(period_rules)

    cont = shot.get("continuity_from") or ""
    if cont:
        components.append(f"Continuity from previous shot: {cont}")

    return ". ".join(c.rstrip(".") for c in components if c) + "."


def negative_prompt(shot: dict) -> str:
    """Shot negative prompt: shot-specific additions + canonical base."""
    specific = (shot.get("negative_prompt") or "").strip()
    if specific:
        return f"{specific}, {DEFAULT_NEGATIVE_PROMPT}"
    return DEFAULT_NEGATIVE_PROMPT

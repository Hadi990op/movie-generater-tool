"""Seed data for the movie "2:13" — Production Bible defaults.

Visual style lock:
  2026: neutral-cool, grey, muted blue, green, black
  2006: warm-neutral, beige, brown, amber, muted cream
  Morning ending: natural daylight, slightly warmer, still realistic.
"""
from __future__ import annotations

IDENTITY_PRESERVE = (
    "facial structure, hairstyle, hairline, eyebrows, eyes, nose, lips, "
    "beard/stubble pattern, skin tone, natural asymmetry, apparent age, "
    "overall recognizable appearance"
)

PROJECT = {
    "project_id": "2_13",
    "title": "2:13",
    "genre": "Supernatural mystery / thriller / emotional drama",
    "language": "English",
    "runtime_target": "15-18 minutes",
    "aspect_ratio": "2.39:1",
    "fps": 24,
    "visual_style": (
        "Photorealistic live-action. Real actors photographed by a professional "
        "live-action cinematographer. Natural film grain, realistic skin textures, "
        "physically believable. NOT cartoon, not 3D animation, not futuristic, "
        "not cyberpunk, not overly stylized, not AI-looking, not beauty-filtered, "
        "no plastic skin, no excessive cinematic effects."),
    "camera_language": (
        "Controlled, motivated camera only. 35mm environment/movement, 50mm "
        "dialogue/normal coverage, 85mm emotional close-up/inserts. Locked, "
        "static, slow push, slow track, controlled handheld, shoulder follow, "
        "pan, tilt, dolly. No random drone shots, no impossible camera movement, "
        "no 360-degree spins, no TikTok-style movement, no random zooms."),
    "lighting_language": (
        "Natural motivated lighting, realistic interior and exterior exposure. "
        "No fake volumetric lighting, no glowing edges."),
    "color_language": (
        "2026: neutral-cool palette - grey, muted blue, green, black. "
        "2006: warm-neutral palette - beige, brown, amber, muted cream. "
        "Morning ending: natural daylight, slightly warmer, still realistic. "
        "No teal-orange blockbuster grade, no neon blue, no heavy orange highlights."),
    "sound_language": (
        "Supernatural audio stays subtle. No ghost voice, no demonic echo, no "
        "magical whoosh. The phone initially sounds completely normal. Audio is "
        "continuous across cuts with sound bridges where appropriate."),
    "editing_language": (
        "Scene-level editing reconstruction of decomposed shot beats. 24fps, "
        "2.39:1, consistent resolution. Trim, replace, reorder, disable shot. "
        "Do not crop important faces or props during aspect conversion."),
    "character_bible": "See characters.json / asset registry",
    "location_bible": "See locations.json / asset registry",
    "prop_bible": "See props.json / asset registry",
    "vehicle_bible": "See vehicles.json / asset registry",
    "continuity_rules": (
        "Every shot has explicit start_state and end_state. Shot N+1 inherits "
        "shot N's end_state as its start_state. Track character position, facing "
        "direction, hand position, object position, wardrobe, lighting, "
        "environment, camera geography, eyeline, physical relationships. Two "
        "periods: 2026 and 2006 — never mix period technology."),
    "negative_constraints": (
        "identity drift, face morphing, age change, hair change, wardrobe change, "
        "extra fingers, missing fingers, duplicate objects, floating objects, "
        "rubber limbs, unnatural walking, weightless movement, background "
        "morphing, lighting inconsistency, impossible shadows, eye-line errors, "
        "camera physics errors, CGI look, cartoon look, plastic skin, beauty "
        "filter, futuristic elements, neon, holograms, excessive lens flare, "
        "over-stylization"),
    "mode": "cinematic",
}

CHARACTERS = [
    {"name": "Daniel", "identity_reference": "CHAR-DAN-01",
     "identity_anchor": "real-person reference image is PRIMARY IDENTITY ANCHOR; "
     "never regenerate identity from scratch; preserve " + IDENTITY_PRESERVE,
     "face_description": "as per reference image",
     "age": "as per reference image", "body_type": "as per reference image",
     "wardrobe": "as per script per period", "personality": "grieving, precise, rational",
     "performance_style": "restrained, naturalistic", "default_expression": "guarded, tired",
     "voice": "calm, low", "continuity_constraints": "never beautify or redesign; "
     "no generic Hollywood actor look; no futuristic styling"},
    {"name": "Ethan", "identity_reference": "CHAR-ETH-01",
     "performance_style": "naturalistic", "default_expression": "open, trusting"},
    {"name": "Sarah", "identity_reference": "CHAR-SAR-01",
     "performance_style": "naturalistic", "default_expression": "warm, alert"},
    {"name": "Frank", "identity_reference": "CHAR-FRA-01",
     "performance_style": "controlled intensity", "default_expression": "watchful"},
    {"name": "Maya", "identity_reference": "CHAR-MAY-01",
     "performance_style": "naturalistic", "default_expression": "quiet, observant"},
]

LOCATIONS = [
    {"name": "Daniel's house", "description": "ordinary suburban house, 2026 period-appropriate"},
    {"name": "Daniel's house 2006", "description": "same house in 2006, period-appropriate "
     "furniture, electronics, phones, vehicles, clothing"},
    {"name": "Street", "description": "quiet suburban street"},
    {"name": "Mailbox", "description": "curbside mailbox"},
]

PROPS = [
    {"name": "watch", "description": "Daniel's watch - continuity anchor prop"},
    {"name": "bag", "description": "canvas bag"},
    {"name": "phone", "description": "phone - 2026 modern but ordinary; 2006 period-appropriate. "
     "Initially sounds completely normal."},
    {"name": "mailbox", "description": "curbside mailbox"},
    {"name": "necklace", "description": "necklace"},
    {"name": "photo", "description": "photograph"},
]

VEHICLES = [
    {"name": "car 2026", "description": "modern but ordinary car"},
    {"name": "car 2006", "description": "period-appropriate 2006 car"},
]

CONTINUITY = {
    "periods": {"2026": "neutral-cool palette, modern but ordinary technology",
                "2006": "warm-neutral palette, period-appropriate technology"},
    "rules": [
        "Shot N+1 start_state = Shot N end_state",
        "Never mix 2026 technology into 2006 scenes",
        "Rain does not disappear between shots unless intentionally scripted",
        "No music automatically; MUSIC_START/STOP/CONTINUE/CUE cues only",
        "Felt piano, cello, restrained analog synth texture, minimal percussion; silence is important",
    ],
}

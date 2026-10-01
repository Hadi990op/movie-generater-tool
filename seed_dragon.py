#!/usr/bin/env python3
"""Seed the fantasy dragon movie "Ashes & Ember" as a new project.

Usage: python3 seed_dragon.py [--parse-only]
Creates project 'dragon' with full asset bible + cinematic plan (no API calls).
"""
import json
import sys
from pathlib import Path

from movie_generator.cinematic.production import ProductionPipeline
from movie_generator.cinematic.decompose import decompose_plan

PROJECT = {
    "project_id": "dragon",
    "title": "Ashes & Ember",
    "genre": "Fantasy / emotional drama",
    "language": "English",
    "runtime_target": "10-12 minutes",
    "aspect_ratio": "2.39:1",
    "fps": 24,
    "visual_style": (
        "Photorealistic live-action fantasy. Real actors and a realistic "
        "practical-feeling dragon photographed by a professional live-action "
        "cinematographer. Ancient medieval world: wooden and stone cottages, "
        "torch and lantern light, wool and leather clothing, pre-gunpowder "
        "weapons (bows, crossbows, spears, blades). Natural film grain, "
        "realistic skin textures, physically believable. NOT cartoon, not 3D "
        "animation, not modern, not futuristic, not AI-looking, not "
        "beauty-filtered, no plastic skin."),
    "camera_language": (
        "Controlled, motivated camera only. 35mm environment/movement, 50mm "
        "dialogue/normal coverage, 85mm emotional close-up/inserts. Locked, "
        "static, slow push, slow track, controlled handheld, shoulder follow, "
        "pan, tilt. No random drone shots, no impossible camera movement."),
    "lighting_language": (
        "Natural motivated lighting: daylight, firelight, torchlight, lantern "
        "light. No fake volumetric lighting, no glowing edges."),
    "color_language": (
        "Earthen fantasy palette: warm browns, muted greens, stone grey, "
        "amber firelight. Night scenes cool with warm fire pockets. "
        "Dawn ending: cold blue morning light warming slightly. "
        "No teal-orange blockbuster grade, no neon."),
    "sound_language": (
        "Dragon sounds are natural animal sounds: growls, chirps, wing beats. "
        "No magical whoosh, no demonic echo. Audio continuous across cuts."),
    "editing_language": (
        "Scene-level editing reconstruction of decomposed shot beats. 24fps, "
        "2.39:1, consistent resolution."),
    "continuity_rules": (
        "Every shot has explicit start_state and end_state. Shot N+1 inherits "
        "shot N's end_state. Track character position, facing, hand position, "
        "prop position, wardrobe, lighting, geography, eyeline. The dragon "
        "grows gradually across the film: tiny hatchling (scenes 3-8), "
        "noticeably larger (scene 8), large young dragon (scenes 11-16). "
        "Never reverse its growth."),
    "negative_constraints": (
        "identity drift, face morphing, wardrobe change, extra fingers, "
        "duplicate objects, floating objects, cartoon look, CGI look, plastic "
        "skin, beauty filter, futuristic elements, modern technology, guns, "
        "gunpowder, neon, holograms, excessive lens flare, over-stylization, "
        "graphic gore, graphic blood"),
    "mode": "cinematic",
}

CHARACTERS = [
    {"name": "LYRA",
     "face_description": "young woman, early-to-mid twenties, natural medieval "
     "villager beauty, wind-chapped cheeks, simple wool dress and leather "
     "boots, hair loosely tied back",
     "wardrobe": "simple wool dress, shawl, hooded cloak in rain, leather boots",
     "performance_style": "naturalistic, heartfelt"},
    {"name": "HUNTER",
     "face_description": "rugged man, late thirties, weathered face, short "
     "beard, leather and fur hunting gear",
     "wardrobe": "leather and fur hunting gear, quiver, heavy coat",
     "performance_style": "controlled intensity"},
    {"name": "AGNES",
     "face_description": "sharp-featured village woman, forties, suspicious "
     "watchful eyes, plain wool dress and headscarf",
     "wardrobe": "plain wool dress, headscarf, shawl",
     "performance_style": "measured, pointed"},
    {"name": "DRAGON-MOTHER",
     "face_description": "enormous ancient dragon, weathered scales in deep "
     "green and bronze, massive wings, large amber eyes",
     "wardrobe": "n/a"},
    {"name": "DRAGON-BABY",
     "face_description": "tiny newly-hatched dragon, oversized emotional "
     "amber eyes, soft dark-green scales, small wings, cute expressive face; "
     "grows gradually to a large young dragon by the finale",
     "wardrobe": "n/a"},
]

LOCATIONS = [
    {"name": "mountain ridge", "description": "high rocky mountain ridge above a green valley, loose scree"},
    {"name": "clearing", "description": "green forest clearing below the ridge"},
    {"name": "village", "description": "medieval village of wooden and stone cottages, muddy lanes"},
    {"name": "cottage", "description": "small one-room cottage interior, hearth fire, wooden beams, bed, crate"},
    {"name": "butcher shop", "description": "small butcher's shop, hanging carcasses, lantern light, wooden counter"},
    {"name": "hunter's house", "description": "hunter's cottage interior, dim, wooden beams"},
]

PROPS = [
    {"name": "shawl", "description": "woolen shawl the girl wraps the baby in"},
    {"name": "ring", "description": "simple metal wedding ring, emotional anchor prop"},
    {"name": "meat", "description": "large wrapped piece of meat"},
    {"name": "basin", "description": "wooden water basin"},
    {"name": "crossbow", "description": "heavy medieval crossbow"},
    {"name": "ballista", "description": "huge fearsome ballista-like giant crossbow"},
]


def main():
    parse_only = "--parse-only" in sys.argv
    script = Path(__file__).parent / "dragon_script.txt"
    if not script.exists():
        script = Path("scripts/dragon_script.txt")
    script_text = script.read_text()

    class _Null:
        def image(self, *a, **k):
            raise RuntimeError("parse-only")
        def video(self, *a, **k):
            raise RuntimeError("parse-only")

    client = _Null() if parse_only else None
    p = ProductionPipeline(_Null(), "projects", "dragon")
    p.init_bible(**dict(PROJECT, characters=CHARACTERS,
                        locations=LOCATIONS, props=PROPS))
    plan = p.parse(script_text)
    plan = decompose_plan(plan)
    p.save_plan(plan)
    (p.dir / "script" / "cinematic_plan.json").write_text(json.dumps(plan, indent=2))
    print(f"dragon project seeded: {plan['total_scenes']} scenes, {plan['total_shots']} shots")
    for sc in plan["scenes"]:
        print(f"  {sc['scene_id']} {sc.get('title','')}: {len(sc['shots'])} shots")


if __name__ == "__main__":
    main()

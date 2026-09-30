#!/usr/bin/env python3
"""Create the 2:13 seed project: bible + script + cinematic plan (no API calls).

Also creates a small test project (SCENE 01, ~7 shots) for the end-to-end
test: parsing -> cinematic JSON -> reference resolution -> keyframe ->
approval -> video -> continuity -> assembly -> export.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from movie_generator.cinematic.production import ProductionPipeline
from movie_generator.cinematic.seed_2_13 import (
    CHARACTERS, CONTINUITY, LOCATIONS, PROJECT, PROPS, VEHICLES)

SCENE_01_SCRIPT = """SCENE 01
TITLE: 2:07 AM
LOCATION: Daniel's house
TIME: 2:07 AM
WEATHER: light rain
SCENE_DURATION: 90

SHOT 01-01
DURATION: 5
LENS: 35mm
FRAMING: medium-wide
CAMERA: STATIC
CHARACTERS: Daniel
ACTION: Daniel sits at the desk looking at an old photograph
PERFORMANCE: still, weighted silence
START_STATE: Daniel seated at the desk, desk lamp off, photograph lying flat
END_STATE: Daniel still seated, photograph in his right hand
AMBIENCE: rain on windows, room tone
MUSIC: none
TRANSITION: cut
COMPLEXITY: 1
GENERATION_LEVEL: 1
REFERENCE_ASSETS: CHAR-DAN-01, PROP-PHOTO-01

SHOT 01-02
DURATION: 2
LENS: 50mm
FRAMING: close-up
CAMERA: STATIC
CHARACTERS: Daniel
ACTION: Daniel turns his head toward the window
PERFORMANCE: alert, restrained
START_STATE: Daniel still seated, photograph in his right hand
END_STATE: Daniel facing the window
SFX: faint gutter drip
TRANSITION: cut
COMPLEXITY: 2
GENERATION_LEVEL: 2
REFERENCE_ASSETS: CHAR-DAN-01

SHOT 01-03
DURATION: 2
LENS: 35mm
FRAMING: medium-wide
CAMERA: SLOW_PUSH
CHARACTERS: Daniel
ACTION: Daniel stands and walks to the window
PERFORMANCE: cautious
START_STATE: Daniel seated, facing the window
END_STATE: Daniel standing at the window, facing out
TRANSITION: cut
COMPLEXITY: 2
GENERATION_LEVEL: 2
REFERENCE_ASSETS: CHAR-DAN-01, LOC-DAN-01

SHOT 01-04
DURATION: 5
LENS: 50mm
FRAMING: medium
CAMERA: STATIC
CHARACTERS: Daniel
ACTION: Daniel looks out at the street through the rain
PERFORMANCE: searching, quiet dread
START_STATE: Daniel standing at the window, facing out
END_STATE: Daniel still at the window, hand on the frame
AMBIENCE: rain steady
TRANSITION: cut
COMPLEXITY: 1
GENERATION_LEVEL: 1
REFERENCE_ASSETS: CHAR-DAN-01, LOC-DAN-01

SHOT 01-05
DURATION: 2
LENS: 50mm
FRAMING: close-up
CAMERA: STATIC
CHARACTERS: Daniel
ACTION: Daniel picks up the phone from the shelf
PERFORMANCE: hesitant
START_STATE: Daniel at the window, hand on the frame
END_STATE: Daniel holding the phone, standing by the shelf
SFX: phone lifted off shelf
TRANSITION: cut
COMPLEXITY: 2
GENERATION_LEVEL: 2
REFERENCE_ASSETS: CHAR-DAN-01, PROP-PHONE-01

SHOT 01-06
DURATION: 5
LENS: 85mm
FRAMING: close-up
CAMERA: STATIC
CHARACTERS: Daniel
ACTION: Daniel listens to the phone, the screen reads 2:13
PERFORMANCE: confusion growing into unease
START_STATE: Daniel holding the phone by the shelf
END_STATE: Daniel holding the phone, expression changed
DIALOGUE: "Hello?"
DIALOGUE_SPEAKER: Daniel
SFX: phone line open, normal tone
TRANSITION: cut
COMPLEXITY: 1
GENERATION_LEVEL: 1
REFERENCE_ASSETS: CHAR-DAN-01, PROP-PHONE-01

SHOT 01-07
DURATION: 2
LENS: 35mm
FRAMING: medium-wide
CAMERA: SLOW_PUSH
CHARACTERS: Daniel
ACTION: Daniel lowers the phone slowly and stares at nothing
PERFORMANCE: shaken, controlled
START_STATE: Daniel holding the phone, expression changed
END_STATE: Daniel standing, phone lowered, facing the room
MUSIC: MUSIC_CUE: felt piano, single note
TRANSITION: cut
COMPLEXITY: 2
GENERATION_LEVEL: 2
REFERENCE_ASSETS: CHAR-DAN-01, PROP-PHONE-01
"""


def create(project_name: str, script: str, write_bible: bool = True) -> Path:
    client = _NullClient()
    p = ProductionPipeline(client, Path(__file__).parent / "projects", project_name)
    if write_bible:
        fields = dict(PROJECT)
        fields["characters"] = CHARACTERS
        fields["locations"] = LOCATIONS
        fields["props"] = PROPS
        p.init_bible(**fields)
        # vehicles + continuity rules
        for v in VEHICLES:
            p.registry.register("VEHICLE", v["name"], description=v["description"])
        (p.dir / "bible" / "continuity.json").write_text(json.dumps(CONTINUITY, indent=2))
    plan = p.parse(script)
    # decompose any complex actions found in the script
    from movie_generator.cinematic.decompose import decompose_plan
    plan = decompose_plan(plan)
    p.save_plan(plan)
    (p.dir / "script" / "cinematic_plan.json").write_text(json.dumps(plan, indent=2))
    return p.dir


class _NullClient:
    """Placeholder client for offline seeding (no API calls made)."""

    def image(self, *a, **kw):
        raise RuntimeError("offline seed: no API calls")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "2_13"
    if name == "2_13":
        script = (Path(__file__).parent / "projects" / "2_13" / "script" /
                  "original_script.txt")
        text = script.read_text() if script.exists() else SCENE_01_SCRIPT
    else:
        text = SCENE_01_SCRIPT
    d = create(name, text)
    plan = json.loads((d / "script" / "cinematic_plan.json").read_text())
    print(f"seeded {name}: {plan['total_scenes']} scenes, {plan['total_shots']} shots")
    print(f"dir: {d}")

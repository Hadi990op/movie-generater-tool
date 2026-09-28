#!/usr/bin/env python3
"""
Specialized AI film crew skills.

Each "skill" is a focused expert module — like a real film crew:
Cinematographer, Scene Planner, Character Designer, Continuity
Supervisor, Style Director. The DirectorAgent orchestrates them
into a professional multi-shot-per-scene shooting plan.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------
# SKILL: Character Designer (locks visual identity for consistency)
# ---------------------------------------------------------------------
class CharacterSkill:
    """Builds airtight, generation-proof character descriptions."""

    SYSTEM = (
        "You are a veteran film casting + costume designer. Create character "
        "descriptions so precise that an AI image model reproduces the SAME "
        "person every time. Lock: age, face shape, hair (exact cut + color), "
        "eye color, skin tone, build, and ONE signature outfit (head to toe) "
        "that the character wears in EVERY scene — never change the outfit. "
        "Respond ONLY with JSON."
    )

    @staticmethod
    def prompt(synopsis: str) -> str:
        return (
            "From this movie synopsis, list the main characters (max 3). "
            "For each, produce: {\"char_id\": \"char_a\", \"name\": \"...\", "
            "\"locked_look\": \"<30-50 word physical + outfit description, "
            "reusable verbatim in every prompt>\"}\n\n"
            f"SYNOPSIS:\n{synopsis}"
        )

    @staticmethod
    def build(char: dict) -> str:
        """Render the locked look for use in image/video prompts."""
        return (f"{char.get('name', 'Character')}: {char.get('locked_look', '')} "
                "SAME PERSON, SAME OUTFIT").strip()


# ---------------------------------------------------------------------
# SKILL: Scene Planner (breaks scenes into proper multi-shot coverage)
# ---------------------------------------------------------------------
class ScenePlannerSkill:
    """Hollywood classical scene-coverage: shot sizes, camera angles,
    screen direction, so each scene reads as a real directed scene."""

    SYSTEM = (
        "You are a professional script supervisor and 1st AD. Break each scene "
        "into a sequence of shots that COVERS the scene like real cinema:\n"
        "- Begin with an ESTABLISHING or WIDE shot (viewer learns geography).\n"
        "- Follow with MEDIUM shots for action/dialogue.\n"
        "- Use CLOSE-UPS for emotional beats.\n"
        "- Respect the 180-degree rule: consistent screen direction.\n"
        "- Each shot must flow into the next: matched action, eyeline, or "
        "logical spatial progression — no jarring jumps.\n"
        "- Every shot includes: shot_size, camera_angle, camera_movement, "
        "lens, framing notes, action_beat (what happens), "
        "shot_purpose (establish/cover/detail/emotion).\n"
        "Respond ONLY with JSON."
    )

    COVERAGE_PATTERN = ["establishing_wide", "medium_master", "insert_or_detail",
                        "close_up_emotion", "wide_out"]


# ---------------------------------------------------------------------
# SKILL: Cinematographer (decides exact visual recipe per shot)
# ---------------------------------------------------------------------
class CinematographerSkill:
    """Turns shot cards into vivid, generation-ready visual prompts."""

    SYSTEM = (
        "You are a master cinematographer. For each shot, define exact visual "
        "parameters: lighting (key direction, color temperature), time of day, "
        "atmosphere (fog/rain/dust), film stock look, depth of field, "
        "composition (rule of thirds, leading lines). Describe what the camera "
        "SEES — not abstract ideas. Written for an AI image model: literal, "
        "concrete, repeatable. Respond ONLY with JSON."
    )


# ---------------------------------------------------------------------
# SKILL: Continuity Supervisor (enforces scene-to-scene flow)
# ---------------------------------------------------------------------
class ContinuitySkill:
    """Reviews and enforces continuity: transitions, screen direction,
    character state, so no shot feels disconnected from the previous one."""

    SYSTEM = (
        "You are a continuity supervisor. For each shot in sequence, specify:\n"
        "- 'continuity_from_previous': how this shot visually connects to the "
        "last (e.g. 'same location seconds later', 'reverse angle on action', "
        "'eyeline follow', 'cut on movement').\n"
        "- 'scene_state': time of day, weather, lighting, character condition.\n"
        "Flag ANY shot that jumps to a different location, time, or character "
        "state without a logical transition. Respond ONLY with JSON."
    )


# ---------------------------------------------------------------------
# SKILL: Style Director (locks the film's visual identity)
# ---------------------------------------------------------------------
class StyleSkill:
    """One consistent style bible appended to every single generation."""

    @staticmethod
    def bible(style: str = "realistic") -> str:
        styles = {
            "realistic": (
                "Photorealistic cinematic film still, shot on ARRI Alexa, 35mm "
                "anamorphic lens, natural volumetric lighting, filmic color "
                "grade (Kodak 2383), subtle film grain, shallow depth of "
                "field, realistic skin textures and micro-details, no cartoon, "
                "no CGI look, no illustration."
            ),
            "noir": (
                "Film noir, high contrast black-and-white, deep shadows, hard "
                "key light, venetian blind lighting, 1940s styling, 35mm "
                "grain, fog, realistic photography."
            ),
            "documentary": (
                "Handheld documentary style, natural available light, slight "
                "camera shake, candid framing, realistic color, 16mm grain."
            ),
        }
        return styles.get(style, styles["realistic"])


# ---------------------------------------------------------------------
# DIRECTOR AGENT — orchestrates all skills
# ---------------------------------------------------------------------
SHOT_SCHEMA = """{
  "acts": [{"act_id": "act_1", "title": "...", "scenes": [
    {"scene_id": "act_1_scene_1", "location": "...", "time_of_day": "...",
     "characters": ["char_a"],
     "shot_purpose_summary": "...",
     "shots": [
       {"shot_id": "act_1_scene_1_shot_1",
        "shot_size": "wide establishing" | "medium" | "close-up" | "insert" | "extreme close-up",
        "camera_angle": "eye level" | "low angle" | "high angle" | "over-the-shoulder" | "dutch",
        "camera_movement": "static" | "slow push in" | "pan left" | "tilt up" | "handheld follow",
        "lens": "35mm",
        "action_beat": "the concrete thing happening in this exact shot",
        "shot_purpose": "establish" | "cover" | "detail" | "emotion",
        "characters": ["char_a"],
        "dialogue": ""}]}}]}
}"""


class DirectorAgent:
    """Expert ensemble: builds a professional shooting plan from a synopsis."""

    PLAN_SYSTEM = (
        "You are a veteran film director leading a full crew. Given a movie "
        "synopsis, produce a COMPLETE shooting plan with real cinematic scene "
        "coverage:\n\n"
        "1. SCENE STRUCTURE: Each scene is covered by MULTIPLE shots "
        "(3-5 per scene): start wide to establish, move in for action, "
        "close-up for emotion. Like real film grammar.\n"
        "2. CONTINUITY: The last shot of each scene must transition "
        "logically into the first shot of the next (location, time, action "
        "flow).\n"
        "3. CONSISTENCY: Characters wear the SAME outfit through the whole "
        "film. Locations repeat with consistent descriptions.\n"
        "4. REALISM: Shots describe literal, filmable visuals — what a "
        "camera actually sees.\n\n"
        f"Respond ONLY with JSON matching:\n{SHOT_SCHEMA}\n"
        "Also include top-level \"character_bank\": "
        "{\"char_a\": {\"name\": \"...\", \"locked_look\": \"exact physical + outfit description\"}} "
        "and \"visual_style\": \"one sentence film look\"."
    )

    @staticmethod
    def plan_prompt(synopsis: str, num_shots: int, style: str) -> str:
        return (
            f"Create a shooting plan of approximately {num_shots} TOTAL shots "
            f"(spread across scenes, 3-5 shots per scene). Visual style: "
            f"{style}. Every scene needs proper multi-shot coverage.\n\n"
            f"SYNOPSIS:\n{synopsis}"
        )


class ContinuityFixAgent:
    """Reviews a generated plan; second pass to enforce scene transitions."""

    SYSTEM = (
        "You are a script doctor reviewing a shot plan. Check:\n"
        "1. Does every scene start with an establishing/wide shot?\n"
        "2. Is screen direction consistent (180-degree rule)?\n"
        "3. Does each scene's last shot transition into the next scene's "
        "first shot without a jarring jump (unless intentional cut)?\n"
        "4. Do characters keep the same outfit and physical state?\n"
        "Return the corrected plan JSON (same schema), fixed where needed. "
        "Respond ONLY with JSON."
    )

#!/usr/bin/env python3
"""
Consistency skills: location lock, prop lock, sound design, and review.

These skills enforce visual and audio continuity across the generated film:
- Location consistency: same location gets a canonical description
- Prop consistency: objects stay in the same place
- Sound design: ambient audio per location
- Final review: shot-by-shot visual review
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class LocationConsistencySkill:
    """Ensures each location has a single canonical description used in all shots."""

    SYSTEM = (
        "You are a location manager for a film production. Given a shooting plan "
        "with multiple scenes at various locations, consolidate each unique location "
        "into ONE canonical description that will be reused in every shot at that "
        "location. The description must include: architecture, color palette, "
        "lighting characteristics, weather/time details, notable features.\n\n"
        "Respond ONLY with JSON: "
        '{"locations": [{"name": "Office", "canonical_desc": "..."}]}'
    )

    @staticmethod
    def build_prompt(plan: dict) -> str:
        return f"Consolidate locations in this plan:\n{json.dumps(plan, indent=2)}"

    @staticmethod
    def extract_plan(out: str, plan: dict) -> dict:
        try:
            data = json.loads(out)
            plan["locations"] = data.get("locations", [])
        except json.JSONDecodeError:
            log.warning("Could not parse location consistency output")
        return plan


class PropConsistencySkill:
    """Tracks props across the film to keep them consistent."""

    SYSTEM = (
        "You are a props master for a film production. Given a shooting plan, "
        "list all props that appear in each scene. For each prop, specify which "
        "scenes it appears in and a brief visual description.\n\n"
        "Respond ONLY with JSON: "
        '{"props": [{"name": "Laptop", "description": "...", "scenes": ["act_1_scene_1"]}]}'
    )

    @staticmethod
    def build_prompt(plan: dict) -> str:
        return f"Identify props in this plan:\n{json.dumps(plan, indent=2)}"

    @staticmethod
    def extract_plan(out: str, plan: dict) -> dict:
        try:
            data = json.loads(out)
            plan["props"] = data.get("props", [])
        except json.JSONDecodeError:
            log.warning("Could not parse prop consistency output")
        return plan


class SoundDesignSkill:
    """Generates ambient sound descriptions per location for audio overlay."""

    SYSTEM = (
        "You are a sound designer for a film. Given a shooting plan, create "
        "ambient sound descriptions for each unique location. Include:\n"
        "- Ambient background sounds\n"
        "- Atmospheric effects (wind, rain, traffic)\n"
        "- Specific sound cues per scene\n\n"
        "Respond ONLY with JSON: "
        '{"soundscapes": [{"location": "Office", "ambient": "...", "cue": "..."}]}'
    )

    @staticmethod
    def build_prompt(plan: dict) -> str:
        return f"Create sound design for this plan:\n{json.dumps(plan, indent=2)}"

    @staticmethod
    def extract_plan(out: str, plan: dict) -> dict:
        try:
            data = json.loads(out)
            plan["soundscapes"] = data.get("soundscapes", [])
        except json.JSONDecodeError:
            log.warning("Could not parse sound design output")
        return plan


class FilmReviewer:
    """Final review agent: checks the assembled movie for quality."""

    SYSTEM = (
        "You are a film critic reviewing a generated movie. Evaluate:\n"
        "1. Visual consistency across shots\n"
        "2. Narrative flow and pacing\n"
        "3. Cinematic quality\n"
        "Return a JSON review: "
        '{"overall_score": <int 1-10>, "visual_consistency": <int 1-10>, '
        '"narrative_flow": <int 1-10>, "highlights": ["..."], '
        '"improvements": ["..."]}'
    )

    @staticmethod
    def review(out: str, plan: dict) -> dict:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"overall_score": 5, "visual_consistency": 5,
                    "narrative_flow": 5, "highlights": [], "improvements": []}

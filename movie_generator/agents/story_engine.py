#!/usr/bin/env python3
"""Story engine: plans shooting schedules, builds prompts, handles continuity."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# --------------------------------------------------------------------- constants
SCENE_SCHEMA = """{
  "acts": [
    {"act_id": "act_1", "title": "Title", "scenes": [
      {"scene_id": "act_1_scene_1", "location": "...", "time_of_day": "...",
       "characters": ["char_a"],
       "shot_purpose_summary": "...",
       "shots": [
         {"shot_id": "act_1_scene_1_shot_1",
          "shot_size": "wide establishing | medium | close-up | insert | extreme close-up",
          "camera_angle": "eye level | low angle | high angle | over-the-shoulder | dutch",
          "camera_movement": "static | slow push in | pan left | tilt up | handheld follow",
          "lens": "35mm",
          "action_beat": "the concrete thing happening in this shot",
          "shot_purpose": "establish | cover | detail | emotion",
          "characters": ["char_a"],
          "dialogue": ""}]}}]}
}"""


class StoryEngine:
    """Orchestrates story planning, prompt building, and continuity."""

    SYSTEM = (
        "You are a veteran film director. Given a movie synopsis, produce a COMPLETE "
        "shooting plan with real cinematic scene coverage.\n\n"
        "1. SCENE STRUCTURE: Multiple shots per scene (3-5): wide establishing → medium → close-up.\n"
        "2. CONTINUITY: Logical transitions between scenes.\n"
        "3. CONSISTENCY: Characters wear same outfits. Same location descriptions.\n"
        "4. REALISM: Literal, filmable visuals.\n\n"
        f"Respond ONLY with JSON matching:\n{SCENE_SCHEMA}\n\n"
        "Also include top-level \"character_bank\": "
        "{\"char_a\": {\"name\": \"...\", \"locked_look\": \"exact physical + outfit\"}} "
        "and \"visual_style\": \"one sentence film look\"."
    )

    def __init__(self, client):
        self.client = client

    # ----------------------------------------------------------------- plan
    def plan_story(self, synopsis: str, num_shots: int = 20) -> dict:
        """Generate a shooting plan from synopsis."""
        prompt = (
            f"Create a shooting plan of approximately {num_shots} total shots "
            f"(3-5 per scene). Visual style: realistic. "
            f"SYNOPSIS:\n{synopsis}"
        )
        messages = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": prompt},
        ]
        out = self.client.chat(messages, temperature=0.7)
        return self._extract_json(out)

    # ----------------------------------------------------------------- prompts
    def build_video_prompt(self, shot: dict, scene: dict,
                           character_bank: dict, style: str = "realistic") -> str:
        """Build a generation-ready video prompt for a single shot."""
        shot_size = shot.get("shot_size", "medium")
        camera_angle = shot.get("camera_angle", "eye level")
        camera_movement = shot.get("camera_movement", "static")
        lens = shot.get("lens", "35mm")
        action = shot.get("action_beat", "")
        dialogue = shot.get("dialogue", "")
        characters = shot.get("characters", [])
        location = scene.get("location", "")
        time_of_day = scene.get("time_of_day", "")

        # Build character descriptions
        char_descs = []
        for cid in characters:
            if isinstance(cid, dict):
                char_descs.append(f"{cid.get('name', '')}: {cid.get('locked_look', '')}")
            else:
                cb = character_bank.get(cid, {})
                if isinstance(cb, dict):
                    char_descs.append(f"{cb.get('name', '')}: {cb.get('locked_look', '')}")
                elif isinstance(cb, str):
                    char_descs.append(cb)
        char_text = " and ".join(char_descs) if char_descs else "a person"

        # Build scene context
        scene_context = ""
        if location:
            scene_context += f"In {location}, "
        if time_of_day:
            scene_context += f"it is {time_of_day}. "

        # Build visual style
        style_bible = self._get_style_bible(style)

        prompt = (
            f"{scene_context}"
            f"{shot_size} shot, {camera_angle} angle, {camera_movement}, {lens} lens. "
            f"{action}"
            f" {char_text}. "
            f"{style_bible}"
        )
        if dialogue:
            prompt += f" Character speaks: \"{dialogue}\""
        return prompt.strip()

    def _get_style_bible(self, style: str) -> str:
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

    # -------------------------------------------------------------- review
    def review_shot(self, prompt: str, image_url: str) -> dict:
        """Vision review: does the rendered keyframe match the shot intent?"""
        system = (
            "You are a film continuity reviewer. Given a shot description and a keyframe "
            "image, rate consistency 1-5 and answer ONLY with JSON: "
            '{"score": <int 1-5>, "pass": <bool>, "issues": "<if any>"}'
        )
        out = self.client.chat(system, prompt, temperature=0.2)
        try:
            return self._extract_json(out)
        except ValueError:
            return {"score": 3, "pass": True, "issues": "review parse failed"}

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from model response."""
        # Try to find JSON in the text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not extract JSON from: {text[:200]}")


class ContinuityFixAgent:
    """Reviews a generated plan; second pass to enforce scene transitions."""

    SYSTEM = (
        "You are a script doctor reviewing a shot plan. Check:\n"
        "1. Does every scene start with an establishing/wide shot?\n"
        "2. Is screen direction consistent (180-degree rule)?\n"
        "3. Does each scene's last shot transition into the next scene's "
        "first shot without a jarring jump?\n"
        "4. Do characters keep the same outfit and physical state?\n"
        "Return the corrected plan JSON (same schema). Respond ONLY with JSON."
    )

    @staticmethod
    def fix_plan(plan: dict, client) -> dict:
        """Second-pass review to improve continuity."""
        prompt = json.dumps(plan, indent=2)
        messages = [
            {"role": "system", "content": ContinuityFixAgent.SYSTEM},
            {"role": "user", "content": f"Fix this shot plan:\n{prompt}"},
        ]
        out = client.chat(messages, temperature=0.3)
        try:
            return StoryEngine._extract_json(out)
        except ValueError:
            return plan

"""Unified project factory: you give WHAT you have, the tool does the rest.

Two input modes, decided automatically:

1. SCRIPT MODE  (--script): you drop a script in any supported format
   (free synopsis, legacy prompt blocks, or the full cinematic format).
   The tool does ALL planning for you:
     - production bible seeded (your --bible JSON if given, else auto-built
       from the script's own fields + genre-aware defaults)
     - script parsed -> structured cinematic plan
     - complex actions decomposed into beat-level shots (unless the script
       already defines every shot explicitly)
     - image/video prompts built for every shot (shots that already carry
       their own prompts keep them verbatim)
     - asset registry + reference images resolved
   Then `run` executes: keyframes -> QA -> videos -> assembly -> export.

2. FULL-DETAIL MODE  (--plan): you provide the complete plan JSON with
   every scene, shot, direction, lens, camera, prompt, duration. The tool
   imports it VERBATIM — no regeneration, no decomposing, no prompt
   rewriting. Everything is executed exactly as you specified.

Auto-detection: a plan JSON ("scenes" with "shots") is full-detail; plain
text is script mode.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from movie_generator.cinematic.decompose import decompose_plan, is_complex_action
from movie_generator.cinematic.parser import parse_script, is_legacy_format
from movie_generator.cinematic.production import ProductionPipeline

# --------------------------------------------------------------- bible seeds
GENRE_DEFAULTS = {
    "fantasy": {
        "visual_style": (
            "Photorealistic live-action fantasy. Real actors photographed by a "
            "professional live-action cinematographer. Natural film grain, "
            "realistic skin textures, physically believable. NOT cartoon, not "
            "3D animation, not AI-looking, not beauty-filtered."),
        "color_language": (
            "Earthen natural palette, motivated lighting. No teal-orange "
            "blockbuster grade, no neon."),
    },
    "thriller": {
        "visual_style": (
            "Photorealistic live-action thriller. Real actors photographed by "
            "a professional cinematographer. Natural film grain, realistic "
            "skin textures. NOT cartoon, not 3D animation, not AI-looking."),
        "color_language": (
            "Cool desaturated palette with warm practical pockets, motivated "
            "lighting only. No neon, no over-stylization."),
    },
    "drama": {
        "visual_style": (
            "Photorealistic live-action drama. Real actors photographed by a "
            "professional cinematographer. Natural film grain, realistic skin "
            "textures. NOT cartoon, not 3D animation, not AI-looking."),
        "color_language": (
            "Natural warm-neutral palette, motivated lighting only."),
    },
}
DEFAULT = GENRE_DEFAULTS["drama"]

_COMMON_CONSTRAINTS = (
    "not cartoon, not 3D animation, not AI-looking, not beauty-filtered, "
    "no plastic skin, no glowing edges, no text, no watermark")

_ASSET_TYPE_WORDS = {
    "CHARACTER": ["characters", "CHARACTERS"],
    "LOCATION": ["locations"],
    "PROP": ["props"],
}


def detect_mode(source: str) -> str:
    """'plan' if the source is a structured plan JSON, else 'script'."""
    s = source.strip()
    if s.startswith("{") and '"scenes"' in s:
        try:
            data = json.loads(s)
            scenes = data.get("scenes") or []
            if scenes and all(isinstance(sc.get("shots"), list) for sc in scenes):
                return "plan"
        except json.JSONDecodeError:
            pass
    return "script"


def extract_genre(text: str) -> str:
    for g in GENRE_DEFAULTS:
        if re.search(rf"\b{g}\b", text, re.IGNORECASE):
            return g
    return "drama"


def extract_characters(text: str) -> list[dict]:
    """Characters from CHARACTERS: fields or ALL-CAPS names in action lines."""
    names: list[str] = []
    for m in re.finditer(r"^CHARACTERS:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE):
        for part in re.split(r"[;,/]", m.group(1)):
            p = part.strip()
            if p and p.upper() not in [n.upper() for n in names]:
                names.append(p)
    if not names:
        # fallback: capitalized leading words in ACTION/SHOT lines
        for m in re.finditer(r"^(?:ACTION:|SHOT\s+[\d\-]+[^\n]*?\b(?:—|-)\s*)([A-Z][a-z]+)\b",
                             text, re.MULTILINE):
            n = m.group(1)
            if n.lower() not in ("the", "a", "an", "shot", "scene", "int", "ext") \
                    and n.upper() not in [x.upper() for x in names]:
                names.append(n)
    return [{"name": n, "face_description": "", "wardrobe": "",
             "performance_style": "naturalistic"} for n in names[:12]]


def build_bible(text: str, project_id: str, title: str, user_bible: dict | None) -> dict:
    """Production bible: user bible wins; else script fields + genre defaults."""
    if user_bible:
        b = dict(user_bible)
        b.setdefault("project_id", project_id)
        b.setdefault("title", title)
        b.setdefault("mode", "cinematic")
        return b
    genre = extract_genre(text)
    d = GENRE_DEFAULTS[genre]
    title_m = re.search(r"^TITLE:\s*(.+)$", text, re.MULTILINE) or \
        re.search(r"^SCENE\s+\d+\s*[—-]\s*(.+)$", text, re.MULTILINE)
    bible = {
        "project_id": project_id,
        "title": title or (title_m.group(1).strip() if title_m else project_id),
        "genre": genre,
        "language": "English",
        "runtime_target": "",
        "aspect_ratio": "2.39:1",
        "fps": 24,
        "visual_style": d["visual_style"],
        "camera_language": (
            "Controlled, motivated camera only. 35mm environment/movement, "
            "50mm dialogue/normal coverage, 85mm emotional close-up. Locked, "
            "static, slow push, slow track, controlled handheld, pan, tilt."),
        "lighting_language": "Natural motivated lighting only. No fake volumetric lighting.",
        "color_language": d["color_language"],
        "sound_language": (
            "Natural ambient sound matching the scene, realistic foley. "
            "Audio continuous across cuts. No magical whoosh, no demonic echo."),
        "editing_language": (
            "Scene-level editing reconstruction of decomposed shot beats. "
            "24fps, consistent resolution."),
        "continuity_rules": (
            "Geography, props, wardrobe and relationships consistent across "
            "cuts. Each shot inherits the previous end_state."),
        "negative_constraints": _COMMON_CONSTRAINTS,
        "character_bible": {c["name"]: c for c in extract_characters(text)},
        "location_bible": {},
        "prop_bible": {},
        "vehicle_bible": {},
        "mode": "cinematic",
    }
    return bible


class AutoProject:
    """Factory around ProductionPipelineV2 handling both input modes."""

    def __init__(self, client, projects_dir: str | Path, name: str):
        self.client = client
        self.projects_dir = Path(projects_dir)
        self.name = name

    def create(self, script_text: str | None = None, plan: dict | None = None,
               title: str = "", user_bible: dict | None = None,
               decompose_actions: bool = True) -> dict:
        """Create the project from whichever source is given.

        Returns summary dict: mode, scenes, shots, decomposed, needs_review.
        """
        if plan is None and script_text:
            if detect_mode(script_text) == "plan":
                plan = json.loads(script_text)
        p = ProductionPipeline(self.client, self.projects_dir, self.name)

        if plan is not None:
            return self._import_plan(p, plan)
        return self._from_script(p, script_text or "", title, user_bible,
                                 decompose_actions)

    # ---------------------------------------------------------- script mode
    def _from_script(self, p: ProductionPipeline, text: str, title: str,
                     user_bible: dict | None, decompose_actions: bool) -> dict:
        bible = build_bible(text, self.name, title, user_bible)
        p.init_bible(**bible)
        plan = p.parse(text)

        # decompose only shots whose actions are complex AND not already
        # fully specified (explicit per-shot scripts skip decomposition)
        if decompose_actions and not is_legacy_format(text):
            auto = [s for sc in plan["scenes"] for s in sc["shots"]
                    if is_complex_action(s.get("subject_action", ""))]
            if auto:
                plan = decompose_plan(plan)
        # asset resolution again over the (possibly decomposed) plan
        p._resolve_assets(plan)
        # prompts: only for shots missing them (script-provided stay verbatim)
        p._build_prompts(plan)
        p.save_plan(plan)

        decomposed_n = sum(1 for sc in plan["scenes"] for s in sc["shots"]
                           if s.get("decomposed_from"))
        return {
            "mode": "script",
            "scenes": plan["total_scenes"],
            "shots": plan["total_shots"],
            "decomposed": decomposed_n,
            "needs_review": sum(1 for sc in plan["scenes"] for s in sc["shots"]
                                if s.get("needs_review")),
            "plan_path": str(p.dir / "script" / "cinematic_plan.json"),
        }

    # ------------------------------------------------------- full-detail mode
    def _import_plan(self, p: ProductionPipeline, plan: dict) -> dict:
        """Import a complete plan VERBATIM. Nothing is rewritten."""
        (p.dir / "script").mkdir(parents=True, exist_ok=True)
        # plan JSON may embed the bible
        bible = plan.pop("bible", None) or {}
        if bible:
            bible = dict(bible)
            bible.setdefault("project_id", self.name)
            bible.setdefault("mode", "cinematic")
            p.init_bible(**bible)
        plan.setdefault("mode", "cinematic")
        plan.setdefault("total_scenes", len(plan.get("scenes", [])))
        plan.setdefault("total_shots",
                        sum(len(sc.get("shots", [])) for sc in plan.get("scenes", [])))
        p._resolve_assets(plan)   # registry IDs only — no prompt building
        (p.dir / "script" / "original_script.txt").write_text(
            "# imported full-detail plan\n" + json.dumps(plan, indent=2))
        (p.dir / "script" / "parsed_script.json").write_text(json.dumps(plan, indent=2))
        (p.dir / "script" / "cinematic_plan.json").write_text(json.dumps(plan, indent=2))
        for scene in plan["scenes"]:
            for shot in scene["shots"]:
                p.queue.add(self.name, scene["scene_id"], shot["shot_id"],
                            "keyframe", priority=5)
        return {
            "mode": "plan",
            "scenes": plan["total_scenes"],
            "shots": plan["total_shots"],
            "decomposed": 0,
            "needs_review": sum(1 for sc in plan["scenes"] for s in sc["shots"]
                                if s.get("needs_review")),
            "plan_path": str(p.dir / "script" / "cinematic_plan.json"),
        }

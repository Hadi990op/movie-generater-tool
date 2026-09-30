"""Production Bible: project-level asset registry and continuity rules.

Assets get persistent IDs (CHAR-DAN-01, LOC-DSP-01, PROP-WATCH-01, VEH-HELI-01)
and shots declare required_assets; the prompt builder injects the right
references automatically.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

ASSET_PREFIXES = {
    "CHARACTER": "CHAR",
    "LOCATION": "LOC",
    "PROP": "PROP",
    "VEHICLE": "VEH",
    "WARDROBE": "WARD",
    "REFERENCE_IMAGE": "REFIMG",
    "REFERENCE_VIDEO": "REFVID",
    "AUDIO": "AUD",
}


def _slug(text: str, maxlen: int = 3) -> str:
    letters = re.sub(r"[^A-Za-z]", "", text).upper()
    return letters[:maxlen] or "XX"


class AssetRegistry:
    """Persistent asset registry for one project."""

    def __init__(self, bible_dir: str | Path):
        self.bible_dir = Path(bible_dir)
        self.bible_dir.mkdir(parents=True, exist_ok=True)
        self.assets_path = self.bible_dir / "assets.json"
        self.assets: dict = {}
        if self.assets_path.exists():
            self.assets = json.loads(self.assets_path.read_text())

    def save(self):
        self.assets_path.write_text(json.dumps(self.assets, indent=2))

    def register(self, asset_type: str, name: str, **fields) -> str:
        """Register an asset, returning its persistent ID. Idempotent on name."""
        for aid, a in self.assets.items():
            if a["type"] == asset_type and a["name"].lower() == name.lower():
                return aid
        prefix = ASSET_PREFIXES.get(asset_type, "AST")
        n = sum(1 for a in self.assets.values() if a["type"] == asset_type) + 1
        aid = f"{prefix}-{_slug(name)}-{n:02d}"
        self.assets[aid] = {"id": aid, "type": asset_type, "name": name, **fields}
        self.save()
        return aid

    def get(self, asset_id: str) -> Optional[dict]:
        return self.assets.get(asset_id)

    def by_type(self, asset_type: str) -> list[dict]:
        return [a for a in self.assets.values() if a["type"] == asset_type]

    def find_by_name(self, name: str) -> Optional[dict]:
        """Match on name, persistent ID (PROP-WATCH-01), or substring of name."""
        name_l = (name or "").lower()
        if name_l in self.assets:
            return self.assets[name_l]
        for a in self.assets.values():
            if a["name"].lower() == name_l or name_l in a["name"].lower():
                return a
        return None

    def reference_image(self, asset_id: str) -> Optional[Path]:
        """Locate the reference image file for an asset, if any."""
        a = self.get(asset_id)
        if not a:
            return None
        refs = self.bible_dir.parent / "references"
        for sub in ("characters", "locations", "props", "vehicles", ""):
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                p = refs / sub / f"{asset_id}{ext}"
                if p.exists():
                    return p
        # any image registered under the asset
        url = a.get("reference_image_url")
        if url:
            return Path(url)
        return None


class ProjectBible:
    """Project-level production bible (bible/project.json)."""

    REQUIRED_KEYS = [
        "project_id", "title", "genre", "language", "runtime_target",
        "aspect_ratio", "fps", "visual_style", "camera_language",
        "lighting_language", "color_language", "sound_language",
        "editing_language", "character_bible", "location_bible",
        "prop_bible", "vehicle_bible", "continuity_rules",
        "negative_constraints",
    ]

    def __init__(self, bible_dir: str | Path):
        self.bible_dir = Path(bible_dir)
        self.bible_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.bible_dir / "project.json"
        self.data: dict = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2))

    def set(self, **fields):
        self.data.update(fields)
        self.save()

    def missing_keys(self) -> list[str]:
        return [k for k in self.REQUIRED_KEYS if k not in self.data]

    def is_complete(self) -> bool:
        return not self.missing_keys()

    @property
    def mode(self) -> str:
        return self.data.get("mode", "legacy")

#!/usr/bin/env python3
"""Render LAST COUNTDOWN from the pre-parsed plan (skips AI planning).

Usage: python render_last_countdown.py
Resumable: existing storyboard/video files are skipped.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from movie_generator.agnes_client import AgnesClient
from movie_generator.pipeline import MovieGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("last_countdown")

ROOT = Path(__file__).parent
PROJECT = "last_countdown"
PLAN_PATH = ROOT / "last_countdown_plan.json"
PROJECTS_DIR = ROOT / "projects"


def main():
    plan = json.loads(PLAN_PATH.read_text())
    client = AgnesClient(str(ROOT / "keys.json"), str(ROOT / "keys_ledger.json"))
    gen = MovieGenerator(client, str(PROJECTS_DIR))
    project_path = PROJECTS_DIR / PROJECT

    flat = []
    for act in plan.get("acts", []):
        for scene in act.get("scenes", []):
            for shot in scene.get("shots", []):
                flat.append((scene, shot))
    total = len(flat)
    log.info("Total shots: %d", total)

    char_bank = plan.get("character_bank", {})
    style_bible = (
        "Photorealistic live-action Hollywood action thriller, shot on ARRI "
        "Alexa, anamorphic lens, 16:9 cinematic frame, natural film grain, "
        "realistic skin textures and micro-details, physically believable "
        "action, natural imperfect lighting, grounded practical-effects "
        "appearance, no cartoon, no CGI look, no illustration, no artificial "
        "HUD, no generated text."
    )

    def build_prompt(scene, shot):
        # shots in this plan carry their own full prompt blocks from the
        # user's production cards — use them directly, add continuity tail
        p = shot["prompt"]
        cont = (" Same woman, same wardrobe, same location, same weapon, "
                "continuous action from previous shot.") if "same woman" not in p.lower() else ""
        return p + cont + " " + style_bible

    # ---- 1. Storyboard keyframes ----
    log.info("Phase 1: storyboard keyframes")
    for i, (scene, shot) in enumerate(flat):
        shot_id = shot["shot_id"]
        kf = project_path / "storyboard" / f"{shot_id}.png"
        kf.parent.mkdir(parents=True, exist_ok=True)
        if kf.exists():
            continue
        prompt = build_prompt(scene, shot)
        try:
            res = client.image(prompt, size="1280x720")  # 16:9
            img_url = (res.get("data") or [{}])[0].get("url")
            if img_url:
                import requests as req
                tmp = kf.with_suffix(kf.suffix + ".part")
                r = req.get(img_url, timeout=300)
                r.raise_for_status()
                tmp.write_bytes(r.content)
                tmp.rename(kf)
                log.info("  [%d/%d] %s keyframe OK", i + 1, total, shot_id)
        except Exception as e:
            log.error("  [%d/%d] %s keyframe FAILED: %s", i + 1, total, shot_id, str(e)[:150])
            time.sleep(10)

    # ---- 2. Video render ----
    log.info("Phase 2: video render")
    for i, (scene, shot) in enumerate(flat):
        shot_id = shot["shot_id"]
        out = project_path / "video" / f"{shot_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            continue
        prompt = build_prompt(scene, shot)
        dur = min(max(shot.get("duration_sec", 3), 2), 8)
        num_frames = round(dur * 3) * 8 + 1  # API rule: 8*n+1
        try:
            url = client.video(prompt, width=1280, height=720,
                               num_frames=num_frames, frame_rate=24,
                               poll_interval=15, poll_timeout=1800)
            import requests as req
            tmp = out.with_suffix(out.suffix + ".part")
            r = req.get(url, timeout=600)
            r.raise_for_status()
            tmp.write_bytes(r.content)
            tmp.rename(out)
            log.info("  [%d/%d] %s video OK (%ds)", i + 1, total, shot_id, dur)
        except Exception as e:
            log.error("  [%d/%d] %s video FAILED: %s", i + 1, total, shot_id, str(e)[:150])
            time.sleep(10)

    # ---- 3. Assemble ----
    log.info("Phase 3: assemble")
    out = gen.assemble(PROJECT, flat)
    log.info("MOVIE READY: %s", out)
    return str(out)


if __name__ == "__main__":
    main()

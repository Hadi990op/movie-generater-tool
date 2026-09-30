#!/usr/bin/env python3
"""Render SECOND SIGHT from the pre-parsed plan (skips AI planning).

Usage: python render_second_sight.py
Resumable: existing storyboard/video files are skipped.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from movie_generator.agnes_client import AgnesClient
from movie_generator.pipeline import MovieGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("second_sight")

ROOT = Path(__file__).parent
PROJECT = "second_sight"
PLAN_PATH = ROOT / "second_sight_plan.json"
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

    locations = {l.get("name", ""): l for l in plan.get("locations", [])}
    props = plan.get("props", [])
    char_bank = plan.get("character_bank", {})
    style_bible = (
        "Photorealistic live-action Hollywood thriller film still, shot on "
        "ARRI Alexa, anamorphic lens, 2.39:1 cinematic widescreen frame, "
        "late afternoon natural warm light gradually becoming golden hour, "
        "filmic color grade (Kodak 2383), subtle film grain, shallow depth "
        "of field, realistic skin textures and micro-details, grounded "
        "physical imperfect action, no cartoon, no CGI look, no illustration, "
        "no artificial HUD."
    )

    def build_prompt(scene, shot):
        p = gen.engine.build_video_prompt(shot, scene, char_bank, "realistic").replace("Duration: 3 sec. ", "")
        p = MovieGenerator._inject_consistency(p, scene, locations, props)
        return p + " " + style_bible

    # ---- 1. Storyboard keyframes ----
    log.info("Phase 1: storyboard keyframes")
    for i, (scene, shot) in enumerate(flat):
        shot_id = shot["shot_id"]
        kf = project_path / "storyboard" / f"{shot_id}.png"
        if kf.exists():
            continue
        prompt = build_prompt(scene, shot)
        try:
            res = client.image(prompt, size="1344x576")  # ~2.39:1
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
        kf = project_path / "storyboard" / f"{shot_id}.png"
        prompt = build_prompt(scene, shot)
        dur = min(max(shot.get("duration_sec", 3), 2), 8)
        num_frames = round(dur * 3) * 8 + 1  # 8*n+1 rule, ~dur seconds at 24fps
        try:
            first_frame_url = None
            if kf.exists():
                import requests as req
                # upload keyframe via public URL is not available; use image gen result URL instead
                res = client.image(prompt, size="1344x576")
                first_frame_url = (res.get("data") or [{}])[0].get("url")
            url = client.video(prompt, width=1248, height=520,
                               num_frames=num_frames, frame_rate=24,
                               first_frame_url=first_frame_url)
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

#!/usr/bin/env python3
"""Full production runner for the dragon movie: all scenes, resumable.

Generates keyframes -> approves -> videos -> assembles -> final export.
Run in background: nohup python3 run_dragon_production.py > prod.log 2>&1 &
"""
import json
import time
from pathlib import Path

from movie_generator.agnes_client import AgnesClient
from movie_generator.cinematic.production import ProductionPipeline

PROJECT_DIR = Path(__file__).parent / "projects" / "dragon"
LOG = Path(__file__).parent / "dragon_prod.log"


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def main():
    client = AgnesClient("keys.json", "keys_ledger.json")
    p = ProductionPipeline(client, "projects", "dragon")
    plan = p.load_plan()

    total = plan["total_shots"]
    done_kf = sum(1 for _, s in p.flat_shots(plan) if s.get("image_status") == "COMPLETED")
    done_vid = sum(1 for _, s in p.flat_shots(plan) if s.get("video_status") == "COMPLETED")
    log(f"resuming: keyframes {done_kf}/{total}, videos {done_vid}/{total}")

    # PHASE 4+5: keyframes (only where missing)
    for scene, shot in p.flat_shots(plan):
        sid = shot["shot_id"]
        if shot.get("image_status") == "COMPLETED":
            continue
        for attempt in range(3):
            try:
                p.generate_keyframe(scene, shot)
                p.approve_keyframe(shot, True, "auto-approved")
                p.save_plan(plan)
                log(f"{sid} keyframe OK")
                break
            except Exception as e:
                log(f"{sid} keyframe attempt {attempt+1} FAIL: {str(e)[:150]}")
                time.sleep(10)
        else:
            shot["image_status"] = "FAILED"
            p.save_plan(plan)

    p.save_plan(plan)

    # PHASE 6: videos (only where missing)
    for scene, shot in p.flat_shots(plan):
        sid = shot["shot_id"]
        if shot.get("video_status") == "COMPLETED":
            continue
        if shot.get("image_status") != "COMPLETED":
            continue
        for attempt in range(3):
            try:
                t0 = time.time()
                p.generate_video(scene, shot)
                p.save_plan(plan)
                log(f"{sid} video OK ({time.time()-t0:.0f}s)")
                break
            except Exception as e:
                log(f"{sid} video attempt {attempt+1} FAIL: {str(e)[:150]}")
                time.sleep(15)
        else:
            shot["video_status"] = "FAILED"
            p.save_plan(plan)

    # PHASE 8+9+10: assemble everything
    try:
        for sc in plan["scenes"]:
            try:
                p.assemble_scene(sc["scene_id"], plan)
                log(f"{sc['scene_id']} assembled")
            except Exception as e:
                log(f"{sc['scene_id']} assemble FAIL: {str(e)[:120]}")
        # concat with relative paths fix
        scenes = [s["scene_id"] for s in plan["scenes"]]
        available = [f"{sid}.mp4" for sid in scenes
                     if (p.dir / "edit" / f"{sid}.mp4").exists()]
        concat = p.dir / "edit" / "concat_scenes.txt"
        concat.write_text("\n".join(f"file '{f}'" for f in available))
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-c", "copy", "-movflags", "+faststart",
                        str(p.dir / "edit" / "final_movie.mp4")],
                       check=True, capture_output=True, timeout=900)
        log("final movie assembled")
        subprocess.run(["ffmpeg", "-y", "-i", str(p.dir / "edit" / "final_movie.mp4"),
                        "-c:v", "libx264", "-crf", "26", "-preset", "fast",
                        "-movflags", "+faststart",
                        str(p.dir / "edit" / "dragon_export.mp4")],
                       check=True, capture_output=True, timeout=1800)
        log("EXPORT COMPLETE: projects/dragon/edit/dragon_export.mp4")
    except Exception as e:
        log(f"export FAIL: {str(e)[:200]}")


if __name__ == "__main__":
    main()

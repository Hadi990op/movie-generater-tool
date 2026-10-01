#!/usr/bin/env python3
"""Resumable v2.5 production run for the dragon project (audio + consistency)."""
import sys, time, traceback
sys.path.insert(0, "/opt/baal-agent/workspace/movie-generater-tool")
from movie_generator.agnes_client_v2 import AgnesClient
from movie_generator.cinematic.production_v2 import ProductionPipelineV2

def log(msg):
    ts = time.strftime("[%H:%M:%S]")
    print(f"{ts} {msg}", flush=True)

c = AgnesClient()
p = ProductionPipelineV2(c, "projects", "dragon")
plan = p.load_plan()

# PHASE 4+5+6: for each shot, keyframe (if missing) -> approve -> video
total = len(p.flat_shots(plan))
log(f"total shots: {total}")
done = 0
for scene, shot in p.flat_shots(plan):
    sid = shot["shot_id"]
    try:
        kf = p.dir / "storyboard" / scene["scene_id"] / f"{sid}.png"
        if not kf.exists():
            p.generate_keyframe(scene, shot)
            log(f"{sid} keyframe OK")
        shot["qa_status"] = "KEYFRAME_APPROVED"
        p.generate_video(scene, shot)
        done += 1
        log(f"{sid} video OK ({done}/{total})")
        p.save_plan(plan)
    except Exception as e:
        log(f"{sid} FAIL: {str(e)[:200]}")
        p.save_plan(plan)
        time.sleep(20)

# retry pass for failed shots (quota may free up over time)
for attempt_round in range(20):
    remaining = [(sc, s) for sc, s in p.flat_shots(plan) if s.get("video_status") != "COMPLETED"]
    if not remaining:
        break
    log(f"retry round {attempt_round+1}: {len(remaining)} shots remaining")
    for scene, shot in remaining:
        sid = shot["shot_id"]
        try:
            kf = p.dir / "storyboard" / scene["scene_id"] / f"{sid}.png"
            if not kf.exists():
                p.generate_keyframe(scene, shot)
            shot["qa_status"] = "KEYFRAME_APPROVED"
            p.generate_video(scene, shot)
            done += 1
            log(f"{sid} video OK ({done}/{total})")
        except Exception as e:
            log(f"{sid} retry FAIL: {str(e)[:150]}")
        p.save_plan(plan)
        time.sleep(30)

# PHASE 8+9+10
log("assembling...")
for s in plan["scenes"]:
    try:
        p.assemble_scene(s["scene_id"], plan)
        log(f"{s['scene_id']} assembled")
    except Exception as e:
        log(f"{s['scene_id']} assembly FAIL: {str(e)[:150]}")
try:
    p.assemble_movie(plan)
    log("final movie assembled")
    out = p.final_export(plan)
    log(f"EXPORT COMPLETE: {out}")
except Exception:
    traceback.print_exc()

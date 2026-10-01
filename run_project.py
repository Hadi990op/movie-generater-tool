#!/usr/bin/env python3
"""Resumable production run: keyframes -> videos -> assembly -> export.

Usage: python run_project.py <name> [retry_rounds]
Resumable: completed shots are skipped; failed shots retry each round.
"""
import sys, time, traceback
sys.path.insert(0, "/opt/baal-agent/workspace/movie-generater-tool")
from movie_generator.agnes_client_v2 import AgnesClient
from movie_generator.cinematic.production_v2 import ProductionPipelineV2


def log(msg):
    print(f"{time.strftime('[%H:%M:%S]')} {msg}", flush=True)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "dragon"
    retry_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    c = AgnesClient()
    p = ProductionPipelineV2(c, "projects", name)
    plan = p.load_plan()

    total = len(p.flat_shots(plan))
    log(f"project '{name}': total shots: {total}")
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

    for rnd in range(retry_rounds):
        remaining = [(sc, s) for sc, s in p.flat_shots(plan)
                     if s.get("video_status") != "COMPLETED"]
        if not remaining:
            break
        log(f"retry round {rnd + 1}: {len(remaining)} shots remaining")
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

    log("assembling...")
    for s in plan["scenes"]:
        try:
            p.assemble_scene(s["scene_id"], plan)
            log(f"{s['scene_id']} assembled")
        except Exception as e:
            log(f"{s['scene_id']} assemble FAIL: {str(e)[:150]}")
    try:
        out = p.assemble_movie(plan)
        log(f"movie assembled: {out}")
        final = p.final_export(plan)
        log(f"final export: {final}")
    except Exception as e:
        log(f"final export FAIL: {str(e)[:200]}")
    log("done")


if __name__ == "__main__":
    main()

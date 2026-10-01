#!/usr/bin/env python3
"""Unified CLI: you give WHAT you have, the tool does the rest.

  # script only — full auto planning (bible, parse, decompose, prompts)
  python3 cli2.py create mymovie --script scripts/myscript.txt

  # script + your own bible (characters, style, constraints)
  python3 cli2.py create mymovie --script scripts/myscript.txt --bible bible.json

  # full-detail plan — every scene/shot/prompt exactly as you made it
  python3 cli2.py create mymovie --plan plan.json

  # then run it (resumable, auto-retries failed shots)
  python3 run_project.py mymovie

  # add a shot to an existing project (script block or full shot JSON)
  python3 cli2.py add-shot mymovie --script new_shots.txt
  python3 cli2.py add-shot mymovie --plan shot.json

  # status of any project
  python3 cli2.py status mymovie
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from movie_generator.agnes_client_v2 import AgnesClient
from movie_generator.cinematic.auto_project import AutoProject, detect_mode
from movie_generator.cinematic.production import ProductionPipeline


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text()


def _load_json(path: str) -> dict:
    return json.loads(_read(path))


def _create(args):
    client = AgnesClient()
    ap = AutoProject(client, "projects", args.name)
    if args.plan:
        plan = _load_json(args.plan)
        summary = ap.create(plan=plan, title=args.title)
    else:
        text = _read(args.script) if args.script else sys.stdin.read()
        # a pasted plan JSON also works with --script (auto-detected)
        bible = _load_json(args.bible) if args.bible else None
        summary = ap.create(script_text=text, title=args.title,
                            user_bible=bible,
                            decompose_actions=not args.no_decompose)
    print(json.dumps(summary, indent=2))
    print(f"\nnext: python3 run_project.py {args.name}")


def _add_shot(args):
    p = ProductionPipeline(AgnesClient(), "projects", args.name)
    plan = p.load_plan()
    if args.plan:
        data = _load_json(args.plan)
        new_shots = []
        if "shots" in data:                      # whole scene block
            scene_id = data.get("scene_id") or f"scene_{len(plan['scenes']) + 1:02d}"
            scene = next((s for s in plan["scenes"] if s["scene_id"] == scene_id), None)
            if not scene:
                scene = {"scene_id": scene_id, "scene_number": len(plan["scenes"]) + 1,
                         "title": data.get("title", ""), "location": "",
                         "time": "", "weather": "", "scene_duration": 0,
                         "characters": [], "props": [], "scene_goal": "",
                         "emotional_goal": "", "continuity_in": "",
                         "continuity_out": "", "shots": []}
                plan["scenes"].append(scene)
            new_shots = data["shots"]
            scene["shots"].extend(new_shots)
        else:                                    # single shot
            new_shots = [data]
            scene_id = data.get("scene_id", plan["scenes"][-1]["scene_id"])
            scene = next((s for s in plan["scenes"] if s["scene_id"] == scene_id),
                         plan["scenes"][-1])
            scene["shots"].append(data)
    else:
        text = _read(args.script) if args.script else sys.stdin.read()
        if detect_mode(text) == "plan":
            data = json.loads(text)
            scene = plan["scenes"][-1]
            scene["shots"].extend(data.get("shots", [data]))
        else:
            # parse as script, merge its scenes/shots into the plan
            from movie_generator.cinematic.parser import parse_script
            parsed = parse_script(text)
            for psc in parsed["scenes"]:
                existing = next((s for s in plan["scenes"]
                                 if s["scene_id"] == psc["scene_id"]), None)
                if existing:
                    existing["shots"].extend(psc["shots"])
                else:
                    plan["scenes"].append(psc)
    # resolve assets + prompts for the new shots only
    p._resolve_assets(plan)
    p._build_prompts(plan)
    plan["total_scenes"] = len(plan["scenes"])
    plan["total_shots"] = sum(len(sc["shots"]) for sc in plan["scenes"])
    p.save_plan(plan)
    print(f"plan updated: {plan['total_scenes']} scenes, {plan['total_shots']} shots")
    print(f"next: python3 run_project.py {args.name}")


def _status(args):
    p = ProductionPipeline(AgnesClient(), "projects", args.name)
    plan = p.load_plan()
    shots = p.flat_shots(plan)
    kf = sum(1 for _, s in shots if s.get("image_status") == "COMPLETED")
    vid = sum(1 for _, s in shots if s.get("video_status") == "COMPLETED")
    review = sum(1 for _, s in shots if s.get("needs_review"))
    print(f"project '{args.name}': {plan.get('total_scenes', '?')} scenes, "
          f"{len(shots)} shots | keyframes: {kf} | videos: {vid} | "
          f"needs_review: {review}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="create project (script or full plan)")
    c.add_argument("name")
    c.add_argument("--script", help="script file (any format) or omit for stdin")
    c.add_argument("--plan", help="full-detail plan JSON (verbatim import)")
    c.add_argument("--bible", help="production bible JSON (optional)")
    c.add_argument("--title", default="")
    c.add_argument("--no-decompose", action="store_true",
                   help="disable complex-action decomposition")

    a = sub.add_parser("add-shot", help="add shots to an existing project")
    a.add_argument("name")
    a.add_argument("--script", help="script block file")
    a.add_argument("--plan", help="shot/scene JSON")

    s = sub.add_parser("status", help="project render status")
    s.add_argument("name")

    args = parser.parse_args()
    {"create": _create, "add-shot": _add_shot, "status": _status}[args.cmd](args)


if __name__ == "__main__":
    main()

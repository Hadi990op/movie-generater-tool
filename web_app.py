#!/usr/bin/env python3
"""Web UI backend — FastAPI serving the movie-generator tool."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from movie_generator.agnes_client import AgnesClient
from movie_generator.pipeline import MovieGenerator

WEB_DIR = Path(__file__).parent / "web"
PROJECTS_DIR = Path(__file__).parent / "projects"
WEB_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AI Movie Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

projects_db = Path(__file__).parent / "projects_db.json"
projects_meta: dict = {}
if projects_db.exists():
    projects_meta = json.loads(projects_db.read_text())

def _save_meta():
    projects_db.write_text(json.dumps(projects_meta, indent=2))

def _init_client():
    keys_file = Path(__file__).parent / "keys.json"
    return AgnesClient(
        str(keys_file),
        str(Path(__file__).parent / "keys_ledger.json"),
    )

class GenerateRequest(BaseModel):
    name: str
    synopsis: str
    num_shots: int = 20
    style: str = "realistic"
    review: bool = True

active_jobs: dict[str, dict] = {}

def _background_generate(job_id: str, name: str, synopsis: str,
                         num_shots: int, style: str):
    active_jobs[job_id] = {
        "status": "running", "progress": 0,
        "messages": [], "output": None, "error": None,
    }
    try:
        client = _init_client()
        gen = MovieGenerator(client, str(PROJECTS_DIR))

        def emit(stage: str, msg: str, progress: int):
            active_jobs[job_id]["messages"].append({"stage": stage, "message": msg})
            active_jobs[job_id]["progress"] = progress

        # 1. Plan
        emit("plan", f"Planning story ({num_shots} shots)...", 5)
        plan = gen.engine.plan_story(synopsis, num_shots)
        project_path = PROJECTS_DIR / name
        plan_path = project_path / "plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2))
        emit("plan", "Story planned successfully", 15)

        flat = []
        for act in plan.get("acts", []):
            for scene in act.get("scenes", []):
                for shot in scene.get("shots", []):
                    flat.append((scene, shot))

        total = len(flat)
        if total == 0:
            raise ValueError("No shots generated. Try a different synopsis.")

        locations = {l.get("name", ""): l for l in plan.get("locations", [])}
        props = plan.get("props", [])

        # 2. Storyboard
        emit("storyboard", f"Generating {total} keyframes...", 20)
        for i, (scene, shot) in enumerate(flat):
            shot_id = shot.get("shot_id", f"shot_{i}")
            kf = project_path / "storyboard" / f"{shot_id}.png"
            if kf.exists():
                continue
            prompt = gen.engine.build_video_prompt(
                shot, scene, plan.get("character_bank", {}), "realistic")
            prompt = MovieGenerator._inject_consistency(
                prompt, scene, locations, props)
            try:
                res = client.image(prompt, size="1280x720")
                img_url = (res.get("data") or [{}])[0].get("url")
                if img_url:
                    import requests as req
                    tmp = kf.with_suffix(kf.suffix + ".part")
                    r = req.get(img_url, timeout=300)
                    r.raise_for_status()
                    tmp.write_bytes(r.content)
                    tmp.rename(kf)
                active_jobs[job_id]["messages"][-1] = {
                    "stage": "storyboard", "message": f"{shot_id}",
                }
            except Exception as e:
                active_jobs[job_id]["messages"].append({
                    "stage": "storyboard_error",
                    "message": f"{shot_id}: {str(e)[:100]}",
                })

        progress = 20 + int((i + 1) / total * 35)
        active_jobs[job_id]["progress"] = progress
        active_jobs[job_id]["messages"].append({
            "stage": "storyboard_done",
            "message": f"{i+1}/{total} keyframes ready",
        })

        # 3. Video render
        emit("video", f"Rendering {total} video shots...", 55)
        for i, (scene, shot) in enumerate(flat):
            shot_id = shot.get("shot_id", f"shot_{i}")
            out = project_path / "video" / f"{shot_id}.mp4"
            if out.exists():
                continue
            kf = project_path / "storyboard" / f"{shot_id}.png"
            prompt = gen.engine.build_video_prompt(
                shot, scene, plan.get("character_bank", {}), "realistic")
            prompt = MovieGenerator._inject_consistency(
                prompt, scene, locations, props)
            try:
                img_url = None
                if kf.exists():
                    res = client.image(prompt, size="1280x720")
                    img_url = (res.get("data") or [{}])[0].get("url")
                url = client.video(prompt, num_frames=121, first_frame_url=img_url)
                import requests as req
                tmp = out.with_suffix(out.suffix + ".part")
                r = req.get(url, timeout=600)
                r.raise_for_status()
                tmp.write_bytes(r.content)
                tmp.rename(out)
                active_jobs[job_id]["messages"][-1] = {
                    "stage": "video", "message": f"{shot_id} ✓",
                }
            except Exception as e:
                active_jobs[job_id]["messages"].append({
                    "stage": "video_error",
                    "message": f"{shot_id}: {str(e)[:100]}",
                })

        progress = 55 + int((i + 1) / total * 35)
        active_jobs[job_id]["progress"] = progress
        active_jobs[job_id]["messages"].append({
            "stage": "video_done",
            "message": f"{i+1}/{total} shots rendered",
        })

        # 4. Assemble
        emit("assemble", "Assembling final movie...", 95)
        out_path = gen.assemble(name, flat)
        active_jobs[job_id]["output"] = str(out_path)

        projects_meta[name] = {
            "output": str(out_path),
            "synopsis": synopsis,
            "shots": total,
            "created": active_jobs[job_id]["messages"][0]["message"] if active_jobs[job_id]["messages"] else "",
        }
        _save_meta()

        active_jobs[job_id]["status"] = "done"
        active_jobs[job_id]["progress"] = 100
        active_jobs[job_id]["messages"].append({
            "stage": "done", "message": "Movie ready!",
        })

    except Exception as e:
        active_jobs[job_id]["status"] = "error"
        active_jobs[job_id]["error"] = str(e)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (WEB_DIR / "index.html").read_text()

@app.get("/api/projects")
async def list_projects():
    return list(projects_meta.keys())

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.post("/api/generate")
async def generate(req: GenerateRequest, bg: BackgroundTasks):
    project_name = req.name.strip()
    if not project_name:
        return JSONResponse({"error": "Name required"}, status_code=400)
    job_id = str(uuid.uuid4())[:8]
    bg.add_task(_background_generate, job_id, project_name,
                req.synopsis, req.num_shots, req.style)
    return {"job_id": job_id, "project_name": project_name}

@app.get("/api/status/{job_id}")
async def status(job_id: str):
    job = active_jobs.get(job_id)
    if not job:
        return {"error": "Job not found"}
    return {
        "job_id": job_id, "status": job["status"],
        "progress": job["progress"], "messages": job["messages"],
        "error": job.get("error"), "output": job.get("output"),
    }

@app.get("/api/projects/{name}/play")
async def play_project(name: str):
    out = PROJECTS_DIR / name / f"{name}.mp4"
    if out.exists():
        return FileResponse(out, media_type="video/mp4", filename=f"{name}.mp4")
    return JSONResponse({"error": "Movie not found"}, status_code=404)

@app.get("/api/projects/{name}/shot/{shot_id}")
async def get_shot(name: str, shot_id: str):
    kf = PROJECTS_DIR / name / "storyboard" / f"{shot_id}.png"
    if kf.exists():
        return FileResponse(kf, media_type="image/png")
    return JSONResponse({"error": "Shot not found"}, status_code=404)

@app.get("/api/projects/{name}/shots")
async def get_shots(name: str):
    p = PROJECTS_DIR / name
    shots = []
    for f in sorted((p / "storyboard").glob("*.png")):
        shot_id = f.stem
        video = p / "video" / f"{shot_id}.mp4"
        shots.append({
            "shot_id": shot_id,
            "keyframe": f"/movie/api/projects/{name}/shot/{shot_id}",
            "video": f"/movie/api/projects/{name}/play/{shot_id}" if video.exists() else None,
        })
    return shots

@app.get("/api/projects/{name}/play/{shot_id}")
async def play_shot(name: str, shot_id: str):
    video = PROJECTS_DIR / name / "video" / f"{shot_id}.mp4"
    if video.exists():
        return FileResponse(video, media_type="video/mp4", filename=f"{shot_id}.mp4")
    return JSONResponse({"error": "Video not found"}, status_code=404)

@app.get("/api/projects/{name}/plan.json")
async def get_plan(name: str):
    plan = PROJECTS_DIR / name / "plan.json"
    if plan.exists():
        return FileResponse(plan, media_type="application/json", filename="plan.json")
    return JSONResponse({"error": "Plan not found"}, status_code=404)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090)

"""Production dashboard API — extends the existing FastAPI web app.

Existing routes in web_app.py stay untouched; these are added via
`app.include_router(production_router, prefix="/api/production")`.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from movie_generator.cinematic.production import ProductionPipeline
from movie_generator.cinematic.continuity import mark_recheck

PROJECTS_DIR = Path(__file__).parent.parent.parent / "projects"

production_router = APIRouter()
active_jobs: dict[str, dict] = {}


def _pipe(name: str) -> ProductionPipeline:
    from movie_generator.agnes_client import AgnesClient
    client = AgnesClient(str(PROJECTS_DIR.parent / "keys.json"),
                         str(PROJECTS_DIR.parent / "keys_ledger.json"))
    return ProductionPipeline(client, str(PROJECTS_DIR), name)


# --------------------------------------------------------------- models
class BibleRequest(BaseModel):
    title: str
    genre: str = ""
    language: str = "English"
    runtime_target: str = ""
    aspect_ratio: str = "2.39:1"
    fps: int = 24
    visual_style: str = ""
    characters: list = []
    locations: list = []
    props: list = []
    mode: str = "cinematic"


class ParseRequest(BaseModel):
    script: str


class ApproveRequest(BaseModel):
    shot_id: str
    approved: bool
    notes: str = ""


class BatchRequest(BaseModel):
    scene_ids: list[str] = []
    kind: str = "storyboard"  # storyboard | approved_videos


class RegenerateRequest(BaseModel):
    shot_id: str
    kind: str = "both"


class AssembleRequest(BaseModel):
    scene_ids: list[str] = []


# --------------------------------------------------------------- phase 0
@production_router.post("/{name}/bible")
async def create_bible(name: str, req: BibleRequest):
    p = _pipe(name)
    fields = req.model_dump()
    data = p.init_bible(**fields)
    return {"bible": data, "missing": p.bible.missing_keys()}


@production_router.get("/{name}/bible")
async def get_bible(name: str):
    p = _pipe(name)
    return {"bible": p.bible.data, "assets": p.registry.assets,
            "missing": p.bible.missing_keys()}


# --------------------------------------------------------------- phase 1+2
@production_router.post("/{name}/parse")
async def parse_script(name: str, req: ParseRequest):
    p = _pipe(name)
    try:
        plan = p.parse(req.script)
        return {"total_scenes": plan.get("total_scenes"),
                "total_shots": plan.get("total_shots"),
                "mode": plan.get("mode"),
                "scenes": [{"scene_id": s["scene_id"], "title": s.get("title", ""),
                            "shots": len(s["shots"])} for s in plan["scenes"]]}
    except Exception as e:
        raise HTTPException(400, str(e)[:300])


@production_router.get("/{name}/plan")
async def get_plan(name: str):
    p = _pipe(name)
    try:
        return p.load_plan()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# --------------------------------------------------------------- progress
@production_router.get("/{name}/progress")
async def progress(name: str):
    p = _pipe(name)
    return p.progress()


@production_router.get("/{name}/shots")
async def list_shots(name: str):
    p = _pipe(name)
    try:
        plan = p.load_plan()
    except FileNotFoundError:
        raise HTTPException(404, "no plan")
    out = []
    for scene, shot in p.flat_shots(plan):
        kf = p.dir / "storyboard" / scene["scene_id"] / f"{shot['shot_id']}.png"
        vid = p.dir / "video" / scene["scene_id"] / f"{shot['shot_id']}.mp4"
        out.append({
            "shot_id": shot["shot_id"], "scene_id": scene["scene_id"],
            "duration": shot.get("duration_seconds"),
            "lens": shot.get("lens"), "camera": shot.get("camera_movement"),
            "characters": shot.get("characters"),
            "action": shot.get("subject_action"),
            "keyframe": f"/movie/api/production/{name}/keyframe/{shot['shot_id']}" if kf.exists() else None,
            "video": f"/movie/api/production/{name}/video/{shot['shot_id']}" if vid.exists() else None,
            "image_status": shot.get("image_status"),
            "video_status": shot.get("video_status"),
            "qa_status": shot.get("qa_status"),
            "needs_review": shot.get("needs_review", []),
        })
    return out


@production_router.get("/{name}/keyframe/{shot_id}")
async def get_keyframe(name: str, shot_id: str):
    p = _pipe(name)
    for kf in p.dir.glob(f"storyboard/*/{shot_id}.png"):
        return FileResponse(kf, media_type="image/png")
    raise HTTPException(404, "keyframe not found")


@production_router.get("/{name}/video/{shot_id}")
async def get_shot_video(name: str, shot_id: str):
    p = _pipe(name)
    for vid in p.dir.glob(f"video/*/{shot_id}.mp4"):
        return FileResponse(vid, media_type="video/mp4")
    raise HTTPException(404, "video not found")


@production_router.get("/{name}/prompt/{shot_id}")
async def get_prompt(name: str, shot_id: str):
    p = _pipe(name)
    plan = p.load_plan()
    for _, shot in p.flat_shots(plan):
        if shot["shot_id"] == shot_id:
            return {"image_prompt": shot.get("image_prompt"),
                    "video_prompt": shot.get("video_prompt"),
                    "negative_prompt": shot.get("negative_prompt"),
                    "start_state": shot.get("start_state"),
                    "end_state": shot.get("end_state"),
                    "references": shot.get("reference_images", [])}
    raise HTTPException(404, "shot not found")


@production_router.get("/{name}/continuity")
async def continuity(name: str):
    p = _pipe(name)
    return p.continuity_report()


# --------------------------------------------------------------- generation
@production_router.post("/{name}/batch")
async def batch(name: str, req: BatchRequest, bg: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    active_jobs[job_id] = {"status": "running", "name": name, "kind": req.kind,
                           "messages": [], "result": None}
    bg.add_task(_bg_batch, job_id, name, req.scene_ids, req.kind)
    return {"job_id": job_id}


def _bg_batch(job_id: str, name: str, scene_ids: list[str], kind: str):
    try:
        p = _pipe(name)
        if kind == "storyboard":
            result = p.batch_storyboards(scene_ids or None)
        else:
            result = p.batch_approved_videos(scene_ids or None)
        active_jobs[job_id]["result"] = result
        active_jobs[job_id]["status"] = "done"
    except Exception as e:
        active_jobs[job_id]["status"] = "error"
        active_jobs[job_id]["error"] = str(e)[:300]


@production_router.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = active_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@production_router.post("/{name}/approve")
async def approve(name: str, req: ApproveRequest):
    p = _pipe(name)
    plan = p.load_plan()
    for _, shot in p.flat_shots(plan):
        if shot["shot_id"] == req.shot_id:
            p.approve_keyframe(shot, req.approved, req.notes)
            p.save_plan(plan)
            if not req.approved:
                # mark later shots for recheck rather than blind approval
                shots = [s for _, s in p.flat_shots(plan)]
                mark_recheck(p.dir, req.shot_id, shots)
            return {"shot": req.shot_id, "qa_status": shot.get("qa_status")}
    raise HTTPException(404, "shot not found")


@production_router.post("/{name}/regenerate")
async def regenerate(name: str, req: RegenerateRequest):
    p = _pipe(name)
    result = p.regenerate_shot(req.shot_id, req.kind)
    plan = p.load_plan()
    shots = [s for _, s in p.flat_shots(plan)]
    mark_recheck(p.dir, req.shot_id, shots)
    p.save_plan(plan)
    return result


@production_router.post("/{name}/retry-failed")
async def retry_failed(name: str, kind: str = None):
    p = _pipe(name)
    n = p.queue.retry_failed(kind)
    return {"requeued": n, "stats": p.queue.stats()}


# --------------------------------------------------------------- assembly
@production_router.post("/{name}/assemble")
async def assemble(name: str, req: AssembleRequest):
    p = _pipe(name)
    plan = p.load_plan()
    scene_ids = req.scene_ids or [s["scene_id"] for s in plan["scenes"]]
    out = []
    for sid in scene_ids:
        try:
            path = p.assemble_scene(sid, plan)
            out.append({"scene": sid, "path": str(path)})
        except Exception as e:
            out.append({"scene": sid, "error": str(e)[:200]})
    return {"assembled": out}


@production_router.post("/{name}/assemble-movie")
async def assemble_movie(name: str):
    p = _pipe(name)
    try:
        out = p.assemble_movie()
        return {"final_movie": str(out)}
    except Exception as e:
        raise HTTPException(400, str(e)[:300])


@production_router.post("/{name}/export")
async def export(name: str):
    p = _pipe(name)
    try:
        out = p.final_export()
        return FileResponse(out, media_type="video/mp4",
                            filename=out.name)
    except Exception as e:
        raise HTTPException(400, str(e)[:300])


@production_router.get("/{name}/play")
async def play(name: str):
    p = _pipe(name)
    for f in (p.dir / "edit").glob("*.mp4"):
        if f.name in ("final_movie.mp4",) or "export" in f.name:
            return FileResponse(f, media_type="video/mp4", filename=f.name)
    raise HTTPException(404, "final movie not found")

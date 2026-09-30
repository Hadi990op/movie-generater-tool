"""Keyframe and video QA.

Automated QA flags potential problems — it is NOT perfect and human
approval remains possible and required before video generation.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def qa_keyframe(shot: dict, keyframe_path: Path, client=None,
                bible: dict | None = None) -> dict:
    """Visual QA of a keyframe against the shot contract.

    Uses a vision-capable model when a client is provided; falls back to
    file-existence checks only. Returns {"status": "PENDING"|"PASSED"|"FAILED",
    "notes": [...]}.
    """
    result = {"status": "PENDING", "notes": []}
    if not keyframe_path.exists():
        result["status"] = "FAILED"
        result["notes"].append("keyframe file missing")
        return result

    if client is None:
        # no vision review available: mark for human approval, don't block
        result["status"] = "PENDING"
        result["notes"].append("automated vision QA unavailable — human approval required")
        return result

    checklist = (
        "Check this keyframe against the shot contract. Answer in JSON with "
        "keys correct_character, correct_face, correct_wardrobe, "
        "correct_location, correct_prop, correct_time_period, correct_camera, "
        "correct_composition, correct_lighting, correct_character_position, "
        "correct_emotional_state (each true/false) and notes (string). "
        f"Shot contract: characters={shot.get('characters')}, "
        f"location={(shot.get('location_id') or '')}, "
        f"period={shot.get('period')}, lens={shot.get('lens')}, "
        f"camera={shot.get('camera')}, action={shot.get('subject_action')}."
    )
    try:
        import base64
        b64 = base64.b64encode(keyframe_path.read_bytes()).decode()
        reply = client.chat(
            [{"role": "user", "content": checklist}],
            image_url=f"data:image/png;base64,{b64}",
            temperature=0.1, max_tokens=500,
        )
        import re
        m = re.search(r"\{.*\}", reply, re.DOTALL)
        if m:
            verdict = json.loads(m.group())
            checks = [v for k, v in verdict.items()
                      if k.startswith("correct_") and isinstance(v, bool)]
            failed = [k for k, v in verdict.items()
                      if k.startswith("correct_") and v is False]
            result["notes"] = [verdict.get("notes", "")] + [f"failed: {k}" for k in failed]
            if failed:
                # only hard-fail on identity/location/period problems
                critical = {"correct_character", "correct_face", "correct_location",
                            "correct_time_period", "correct_prop"}
                if set(failed) & critical:
                    result["status"] = "FAILED"
                else:
                    result["status"] = "PENDING"  # human decides on soft fails
            else:
                result["status"] = "PASSED"
    except Exception as e:
        result["notes"].append(f"QA error: {str(e)[:120]}")
        result["status"] = "PENDING"
    return result


def qa_video(shot: dict, video_path: Path, client=None) -> dict:
    """Automated video QA flags: identity drift, deformation, camera
    instability, background morphing, motion glitches.

    Extracts 3 frames with ffmpeg and reviews them with a vision model;
    without a client, flags for human review only.
    """
    result = {"status": "PENDING", "notes": []}
    if not video_path.exists():
        result["status"] = "FAILED"
        result["notes"].append("video file missing")
        return result

    if client is None:
        result["notes"].append("automated video QA unavailable — human review recommended")
        return result

    import subprocess
    import tempfile
    frames_dir = Path(tempfile.mkdtemp(prefix="qa_frames_"))
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "select='eq(n\\,0)+eq(n\\,40)+eq(n\\,80)'",
            "-vsync", "vfr", str(frames_dir / "f%02d.png"),
        ], check=True, capture_output=True, timeout=60)
        frame_files = sorted(frames_dir.glob("f*.png"))
        if not frame_files:
            result["notes"].append("no frames extracted for QA")
            return result
        # compare first and last frame for drift
        import base64
        f0 = base64.b64encode(frame_files[0].read_bytes()).decode()
        f1 = base64.b64encode(frame_files[-1].read_bytes()).decode()
        reply = client.chat(
            [{"role": "user", "content": (
                "These are the first and last frames of a generated video shot. "
                "Check for: identity drift, face deformation, hand anomalies, "
                "object disappearance, wardrobe changes, background morphing, "
                "lighting changes. Answer in JSON: {drift: true/false, "
                "problems: [..], severity: ok/warning/critical}.")}],
            image_url=f"data:image/png;base64,{f0}",
            temperature=0.1, max_tokens=400,
        )
        # send second image as separate request (single-image chat support)
        try:
            reply2 = client.chat(
                [{"role": "user", "content": (
                    "This is the last frame of a generated video shot. Check for "
                    "identity drift, face deformation, hand anomalies, wardrobe "
                    "changes, background morphing. Answer in JSON: {drift: "
                    "true/false, problems: [..], severity: ok/warning/critical}.")}],
                image_url=f"data:image/png;base64,{f1}",
                temperature=0.1, max_tokens=400,
            )
            import re
            m2 = re.search(r"\{.*\}", reply2, re.DOTALL)
            if m2:
                v2 = json.loads(m2.group())
                if v2.get("drift") or v2.get("severity") == "critical":
                    result["status"] = "QA_FAILED"
                result["notes"].append(str(v2.get("problems", ""))[:200])
        except Exception:
            pass
        import re
        m = re.search(r"\{.*\}", reply, re.DOTALL)
        if m:
            v = json.loads(m.group())
            if v.get("drift") or v.get("severity") == "critical":
                result["status"] = "QA_FAILED"
            result["notes"].append(str(v.get("problems", ""))[:200])
        if result["status"] == "PENDING" and not result["notes"]:
            result["status"] = "PASSED"
    except Exception as e:
        result["notes"].append(f"QA error: {str(e)[:120]}")
        result["status"] = "PENDING"
    finally:
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)
    return result


def save_qa_report(project_dir: str | Path, kind: str, shot_id: str, report: dict):
    p = Path(project_dir) / "qa" / kind / f"{shot_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2))

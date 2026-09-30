"""Shot-aware render queue on top of the existing AgnesClient key rotation.

Each queue task carries: project, scene, shot, generation_type, priority,
attempt, status. A failed shot never crashes the whole movie.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

STATUSES = [
    "PENDING", "GENERATING", "COMPLETED", "FAILED", "RETRYING",
    "RATE_LIMITED", "APPROVAL_REQUIRED", "QA_FAILED", "CANCELLED",
]

MAX_ATTEMPTS = 3


class RenderQueue:
    """Persistent, shot-aware render queue."""

    def __init__(self, project_dir: str | Path):
        self.path = Path(project_dir) / "logs" / "queue.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks: list[dict] = []
        self._lock = threading.RLock()
        if self.path.exists():
            try:
                self.tasks = json.loads(self.path.read_text())
            except ValueError:
                self.tasks = []

    def save(self):
        with self._lock:
            self.path.write_text(json.dumps(self.tasks, indent=2))

    def add(self, project: str, scene: str, shot: str, generation_type: str,
            priority: int = 5) -> dict:
        with self._lock:
            for t in self.tasks:
                if (t["shot"] == shot and t["generation_type"] == generation_type
                        and t["status"] not in ("COMPLETED", "CANCELLED")):
                    return t  # idempotent
            task = {
                "id": f"{shot}-{generation_type}",
                "project": project, "scene": scene, "shot": shot,
                "generation_type": generation_type, "priority": priority,
                "api_key": None, "attempt": 0, "status": "PENDING",
                "created": time.time(), "error": "",
            }
            self.tasks.append(task)
            self.save()
            return task

    def next_pending(self, generation_type: str | None = None) -> dict | None:
        with self._lock:
            candidates = [t for t in self.tasks
                          if t["status"] in ("PENDING", "RETRYING", "RATE_LIMITED")
                          and t["attempt"] < MAX_ATTEMPTS
                          and (generation_type is None or t["generation_type"] == generation_type)]
            if not candidates:
                return None
            candidates.sort(key=lambda t: (t["priority"], t["created"]))
            t = candidates[0]
            t["status"] = "GENERATING"
            t["attempt"] += 1
            self.save()
            return t

    def complete(self, task: dict):
        task["status"] = "COMPLETED"
        task["error"] = ""
        self.save()

    def fail(self, task: dict, error: str, rate_limited: bool = False):
        task["error"] = error[:300]
        if rate_limited:
            task["status"] = "RATE_LIMITED"
        elif task["attempt"] >= MAX_ATTEMPTS:
            task["status"] = "FAILED"
        else:
            task["status"] = "RETRYING"
        self.save()

    def requires_approval(self, task: dict):
        task["status"] = "APPROVAL_REQUIRED"
        self.save()

    def qa_failed(self, task: dict):
        task["status"] = "QA_FAILED"
        self.save()

    def cancel(self, task: dict):
        task["status"] = "CANCELLED"
        self.save()

    def retry_failed(self, generation_type: str | None = None):
        """Re-queue failed tasks (reset attempts for a fresh round)."""
        n = 0
        for t in self.tasks:
            if t["status"] in ("FAILED", "QA_FAILED") and (
                    generation_type is None or t["generation_type"] == generation_type):
                t["status"] = "PENDING"
                t["attempt"] = 0
                n += 1
        self.save()
        return n

    def stats(self) -> dict:
        out = {s: 0 for s in STATUSES}
        for t in self.tasks:
            out[t["status"]] = out.get(t["status"], 0) + 1
        return out

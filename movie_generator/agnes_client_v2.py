#!/usr/bin/env python3
"""Agnes AI gateway client v2 — rebuilt for Agnes Video 2.5 API.

Video 2.5 contract (per wiki.agnes-ai.com/en/docs/agnes-video-25):
  POST /v1/videos  {model, prompt, mode: text|keyframe|reference,
                    seconds: "4"-"12", size: 720P|1080P|1K|2K,
                    aspect_ratio: 21:9|16:9|..., seed, n: 1}
  keyframe mode: first_frame / last_frame image URLs (publicly reachable)
  reference mode: images[] / audios[] / videos[].url
  GET /agnesapi?video_id=<ID>&model_name=<MODEL>  -> status completed|failed, url
  Native audio: describe ambient/action sound in the prompt.
  Forbidden: width, height, fps, num_frames, quality, pixel sizes in size.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://apihub.agnes-ai.com/v1"
POLL_URL = "https://apihub.agnes-ai.com/agnesapi"
MAX_ATTEMPTS = 3

log = logging.getLogger(__name__)

MODELS = {
    "chat": ["agnes-2.5-flash", "agnes-2.5-pro", "agnes-3.0-flash"],
    "image": ["agnes-image-2.5-flash", "agnes-image-2.1-flash", "agnes-image-2.1-pro"],
    "video": ["agnes-video-2.5-flash", "agnes-video-2.5"],
}

VIDEO_SIZES = ("720P", "1080P", "1K", "2K")
ASPECT_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")

# Publicly-reachable base for media URLs served to Agnes (keyframe mode needs this)
MEDIA_BASE_URL = "https://maze-labor-three-crouch.2n6.me/moviedata"


class AllKeysExhausted(Exception):
    pass


@dataclasses.dataclass
class KeyState:
    name: str
    api_key: str
    plan: str = "free"
    disabled: bool = False
    video_seconds_used_today: float = 0
    requests_today: int = 0
    cooldown_until: float = 0.0
    last_used: float = 0.0

    @property
    def usage(self) -> dict:
        return {
            "key": self.name,
            "disabled": self.disabled,
            "video_seconds_used_today": round(self.video_seconds_used_today, 2),
            "requests_today": self.requests_today,
        }


class AgnesClient:
    """Agnes AI gateway client with transparent multi-key rotation (v2 API)."""

    def __init__(self, keys_file: str | Path = "keys.json", ledger_file: str | Path = "keys_ledger.json"):
        self.keys_file = Path(keys_file)
        self.ledger_file = Path(ledger_file)
        self.keys: list[KeyState] = []
        self._lock = threading.RLock()
        self._load_keys()
        self._load_ledger()

    # ---------------------------------------------------------------- keys
    def _load_keys(self):
        if not self.keys_file.exists():
            return
        raw = json.loads(self.keys_file.read_text())
        keys = raw if isinstance(raw, list) else raw.get("keys", [])
        self.keys = [
            KeyState(
                name=k.get("name", f"k{len(self.keys)+1}"),
                api_key=k["api_key"],
                plan=k.get("plan", "free"),
            )
            for k in keys
            if k.get("api_key")
        ]
        log.info("Loaded %d Agnes API keys", len(self.keys))

    def _load_ledger(self):
        if not self.ledger_file.exists():
            return
        try:
            data = json.loads(self.ledger_file.read_text())
            if data.get("date") != str(date.today()):
                return
            for st in data.get("keys", []):
                k = self.get_key(st["name"])
                if k:
                    k.video_seconds_used_today = st.get("video_seconds_used_today", 0)
                    k.requests_today = st.get("requests_today", 0)
        except (ValueError, KeyError):
            pass

    def save_ledger(self):
        data = {
            "date": str(date.today()),
            "keys": [
                {"name": k.name, "video_seconds_used_today": k.video_seconds_used_today,
                 "requests_today": k.requests_today}
                for k in self.keys
            ],
        }
        self.ledger_file.write_text(json.dumps(data, indent=2))

    def get_key(self, name: str) -> Optional[KeyState]:
        for k in self.keys:
            if k.name == name:
                return k
        return None

    def _pick_key(self, purpose: str, seconds: float = 0) -> KeyState:
        """Least-loaded active key; rotate on failure instead of giving up."""
        with self._lock:
            now = time.time()
            candidates = [k for k in self.keys
                          if not k.disabled and k.cooldown_until <= now]
            if not candidates:
                raise AllKeysExhausted("No active Agnes key available.")
            candidates.sort(key=lambda k: (k.video_seconds_used_today, k.requests_today))
            k = candidates[0]
            k.last_used = now
            k.requests_today += 1
            if purpose == "video":
                k.video_seconds_used_today += seconds
            self.save_ledger()
            return k

    def _handle_error(self, k: KeyState, status: int, body: str = ""):
        if status in (401, 403):
            if "insufficient_user_quota" in body:
                # quota exhausted (may reset daily) — cooldown, don't kill key
                k.cooldown_until = time.time() + 1800
                log.warning("Key %s out of quota — cooldown 30min", k.name)
            else:
                k.disabled = True
                log.warning("Key %s disabled (HTTP %d)", k.name, status)
        elif status == 429:
            # short cooldown then rotate to another key
            k.cooldown_until = time.time() + 120
            log.warning("Key %s cooling down 2min (429)", k.name)
        self.save_ledger()

    def refund_video(self, key_name: str, seconds: float):
        k = self.get_key(key_name)
        if k:
            k.video_seconds_used_today = max(0, k.video_seconds_used_today - seconds)
            self.save_ledger()

    # ---------------------------------------------------------------- chat
    def chat(self, messages, model: str = "agnes-2.5-flash", image_url: str | None = None,
             temperature: float = 0.7, max_tokens: int = 4096, retries: int = MAX_ATTEMPTS) -> str:
        if model not in MODELS["chat"]:
            raise ValueError(f"Unknown chat model: {model}")
        if image_url and len(messages) == 1:
            messages = [{"role": "user", "content": [
                {"type": "text", "text": messages[-1]["content"]},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}]
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens}
        last_err = None
        for attempt in range(retries):
            try:
                k = self._pick_key("chat")
            except AllKeysExhausted:
                raise
            try:
                r = requests.post(f"{BASE_URL}/chat/completions",
                                  headers={"Authorization": f"Bearer {k.api_key}"},
                                  json=body, timeout=120)
            except requests.RequestException as e:
                last_err = f"network: {e}"
                time.sleep(5)
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            self._handle_error(k, r.status_code)
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(min(2 ** (attempt + 1), 30))
        raise RuntimeError(f"chat failed after {retries} attempts: {last_err}")

    # --------------------------------------------------------------- image
    def image(self, prompt: str, size: str = "1024x1024", model: str = "agnes-image-2.5-flash",
              retries: int = MAX_ATTEMPTS, image_url: str | None = None) -> dict:
        if model not in MODELS["image"]:
            raise ValueError(f"Unknown image model: {model}")
        body = {"model": model, "prompt": prompt, "size": size}
        if image_url:
            body["image"] = image_url
        last_err = None
        for attempt in range(retries):
            try:
                k = self._pick_key("image")
            except AllKeysExhausted:
                raise
            try:
                r = requests.post(f"{BASE_URL}/images/generations",
                                  headers={"Authorization": f"Bearer {k.api_key}"},
                                  json=body, timeout=180)
            except requests.RequestException as e:
                last_err = f"network: {e}"
                time.sleep(5)
                continue
            if r.status_code == 200:
                return r.json()
            self._handle_error(k, r.status_code)
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(min(2 ** (attempt + 1), 30))
        raise RuntimeError(f"image failed: {last_err}")

    # --------------------------------------------------------------- video
    def video(self, prompt: str, seconds: str = "5", mode: str = "text",
              size: str = "720P", aspect_ratio: str = "21:9", seed: int | None = None,
              first_frame_url: str | None = None, last_frame_url: str | None = None,
              reference_images: list[str] | None = None,
              model: str = "agnes-video-2.5-flash",
              poll_interval: int = 8, poll_timeout: int = 1800) -> str:
        """Create async Video 2.5 task, poll until ready. Returns video URL."""
        if mode not in ("text", "keyframe", "reference"):
            raise ValueError(f"Invalid video mode: {mode}")
        if size not in VIDEO_SIZES:
            raise ValueError(f"Invalid size: {size}")
        if aspect_ratio not in ASPECT_RATIOS:
            raise ValueError(f"Invalid aspect_ratio: {aspect_ratio}")

        body: dict = {
            "model": model,
            "prompt": prompt,
            "mode": mode,
            "seconds": str(seconds),
            "size": size,
            "aspect_ratio": aspect_ratio,
            "n": 1,
        }
        if seed is not None:
            body["seed"] = seed
        if mode == "keyframe":
            if first_frame_url:
                body["first_frame"] = first_frame_url
            if last_frame_url:
                body["last_frame"] = last_frame_url
            if not (first_frame_url or last_frame_url):
                raise ValueError("keyframe mode requires first_frame or last_frame")
        elif mode == "reference":
            if reference_images:
                body["images"] = reference_images
            else:
                raise ValueError("reference mode requires reference media")

        billable = float(seconds)
        last_err = None
        for attempt in range(6):
            try:
                k = self._pick_key("video", seconds=billable)
            except AllKeysExhausted as e:
                raise e
            try:
                r = requests.post(f"{BASE_URL}/videos",
                                  headers={"Authorization": f"Bearer {k.api_key}"},
                                  json=body, timeout=120)
            except requests.RequestException as e:
                last_err = f"network: {e}"
                time.sleep(10)
                continue
            if r.status_code == 200:
                data = r.json()
                video_id = data.get("video_id") or data.get("id") or data.get("task_id")
                if not video_id:
                    self.refund_video(k.name, billable)
                    raise RuntimeError(f"No video_id in response: {str(data)[:300]}")
                return self._poll_video(video_id, model, k, poll_interval, poll_timeout)
            self._handle_error(k, r.status_code, body=r.text[:400])
            self.refund_video(k.name, billable)
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            # 400 = request problem, not key problem: retrying with another key won't help
            if r.status_code == 400:
                break
            if r.status_code == 503:
                time.sleep(min(60 * (attempt + 1), 180))
                continue
            time.sleep(min(2 ** (attempt + 1), 30))
        raise RuntimeError(f"video task create failed: {last_err}")

    def _poll_video(self, video_id: str, model: str, k: KeyState, poll_interval: int,
                    poll_timeout: int) -> str:
        start = time.time()
        while time.time() - start < poll_timeout:
            time.sleep(poll_interval)
            try:
                r = requests.get(POLL_URL, params={"video_id": video_id, "model_name": model},
                                 headers={"Authorization": f"Bearer {k.api_key}"}, timeout=60)
            except requests.RequestException:
                continue
            if r.status_code != 200:
                if r.status_code == 429:
                    time.sleep(poll_interval * 2)
                continue
            d = r.json()
            status = str(d.get("status", "")).lower()
            if status == "completed":
                url = d.get("url") or d.get("video_url") or d.get("output", {}).get("video_url")
                if url:
                    return url
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Video task failed: {d}")
        raise TimeoutError(f"Video polling timed out for {video_id}")

    # --------------------------------------------------------------- status
    def status(self) -> list[dict]:
        return [k.usage for k in self.keys]

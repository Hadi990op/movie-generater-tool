#!/usr/bin/env python3
"""Agnes AI gateway client with multi-key rotation and quota tracking."""
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

BASE_URL = "https://api.agnes.ai/v1"
POLL_URL = "https://api.agnes.ai/videos/status"
MAX_ATTEMPTS = 3
DEFAULT_VIDEO_RPM = 10
VIDEO_DAILY_SECONDS = 1000.0

log = logging.getLogger(__name__)

MODELS = {
    "chat": ["agnes-2.5-flash", "agnes-2.5-pro"],
    "image": ["agnes-image-2.1-flash", "agnes-image-2.1-pro"],
    "video": ["agnes-video-v2.0"],
}


class AllKeysExhausted(Exception):
    pass


@dataclasses.dataclass
class KeyState:
    name: str
    api_key: str
    plan: str = "free"                    # free | token | enterprise
    video_rpm: int = DEFAULT_VIDEO_RPM
    disabled: bool = False                # 401/403 => disabled
    # runtime usage ledger (persisted separately)
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
    """Agnes AI gateway client with transparent multi-key rotation."""

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
                video_rpm=k.get("video_rpm", DEFAULT_VIDEO_RPM),
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
                return  # new day -> fresh quota
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
        """Least-loaded active key with quota available for this request."""
        with self._lock:
            now = time.time()
            candidates = []
            for k in self.keys:
                if k.disabled or k.cooldown_until > now:
                    continue
                if purpose == "video" and k.video_seconds_used_today + seconds > VIDEO_DAILY_SECONDS:
                    continue
                candidates.append(k)
            if not candidates:
                raise AllKeysExhausted(
                    "No Agnes key has remaining quota (video_seconds/day or cooldown)."
                )
            candidates.sort(key=lambda k: (k.video_seconds_used_today, k.requests_today))
            k = candidates[0]
            k.last_used = now
            k.requests_today += 1
            if purpose == "video":
                k.video_seconds_used_today += seconds  # conservative reserve
            self.save_ledger()
            return k

    def _handle_error(self, k: KeyState, status: int):
        if status in (401, 403):
            k.disabled = True
            log.warning("Key %s disabled (HTTP %d)", k.name, status)
        elif status == 429:
            k.cooldown_until = time.time() + 300
            log.warning("Key %s cooling down 5min (429)", k.name)
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
        if image_url:
            messages = [{"role": "user", "content": [
                {"type": "text", "text": messages[-1]["content"]},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}] if len(messages) == 1 else messages

        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens}
        last_err = None
        for _ in range(retries):
            try:
                k = self._pick_key("chat")
            except AllKeysExhausted as e:
                raise e
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
            time.sleep(2 ** (_ or 1))
        raise RuntimeError(f"chat failed after {retries} attempts: {last_err}")

    # --------------------------------------------------------------- image
    def image(self, prompt: str, size: str = "1280x720", model: str = "agnes-image-2.1-flash",
              retries: int = MAX_ATTEMPTS) -> dict:
        if model not in MODELS["image"]:
            raise ValueError(f"Unknown image model: {model}")
        body = {"model": model, "prompt": prompt, "size": size}
        last_err = None
        for _ in range(retries):
            try:
                k = self._pick_key("image")
            except AllKeysExhausted as e:
                raise e
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
            time.sleep(2 ** (_ or 1))
        raise RuntimeError(f"image failed: {last_err}")

    # ---------------------------------------------------------------- video
    def video(self, prompt: str, width: int = 1152, height: int = 768,
              num_frames: int = 121, frame_rate: int = 24, image_url: str | None = None,
              first_frame_url: str | None = None, poll_interval: int = 15,
              poll_timeout: int = 1800) -> str:
        """Create async video task, poll until ready. Returns video download URL."""
        duration = num_frames / frame_rate
        body = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }
        if image_url:
            body["image_url"] = image_url
        if first_frame_url:
            body["first_frame_url"] = first_frame_url

        k = self._pick_key("video", seconds=duration)
        r = requests.post(f"{BASE_URL}/videos",
                          headers={"Authorization": f"Bearer {k.api_key}"},
                          json=body, timeout=120)
        if r.status_code != 200:
            self._handle_error(k, r.status_code)
            self.refund_video(k.name, duration)
            raise RuntimeError(f"video task create failed: {r.status_code} {r.text[:200]}")

        data = r.json()
        video_id = data.get("video_id") or data.get("id") or data.get("task_id")
        if not video_id:
            self.refund_video(k.name, duration)
            raise RuntimeError(f"No video_id in response: {str(data)[:300]}")

        return self._poll_video(video_id, k, poll_interval, poll_timeout)

    def _poll_video(self, video_id: str, k: KeyState, poll_interval: int,
                    poll_timeout: int) -> str:
        start = time.time()
        while time.time() - start < poll_timeout:
            time.sleep(poll_interval)
            try:
                r = requests.get(POLL_URL, params={"video_id": video_id},
                                 headers={"Authorization": f"Bearer {k.api_key}"},
                                 timeout=60)
            except requests.RequestException:
                continue
            if r.status_code != 200:
                continue
            d = r.json()
            status = str(d.get("status", "")).lower()
            if status in ("succeeded", "success", "done", "completed", "finished"):
                url = d.get("video_url") or d.get("url") or d.get("output", {}).get("video_url")
                if url:
                    return url
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Video task failed: {d}")
        raise TimeoutError(f"Video polling timed out for {video_id}")

    # --------------------------------------------------------------- status
    def status(self) -> list[dict]:
        return [k.usage for k in self.keys]

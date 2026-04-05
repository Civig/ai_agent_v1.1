from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


@dataclass
class HealthSampler:
    host: str
    output_dir: Path
    verify: bool
    interval_seconds: float
    queue_runaway_threshold: int
    not_ready_grace_seconds: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    stop_condition: str = ""

    def __post_init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started_at = 0.0
        self._not_ready_since: float | None = None
        self.ready_samples: list[dict[str, object]] = []
        self.health_samples: list[dict[str, object]] = []
        self._ready_path = self.output_dir / "health_ready.jsonl"
        self._health_path = self.output_dir / "health.jsonl"

    def start(self) -> None:
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="health-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds * 2))

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self._sample_endpoint("/health/ready", self._ready_path, self.ready_samples, ready_endpoint=True)
            self._sample_endpoint("/health", self._health_path, self.health_samples, ready_endpoint=False)
            self.stop_event.wait(self.interval_seconds)

    def _sample_endpoint(
        self,
        path: str,
        target_file: Path,
        bucket: list[dict[str, object]],
        *,
        ready_endpoint: bool,
    ) -> None:
        ts_ms = int(time.time() * 1000)
        sample = {"ts_ms": ts_ms, "path": path, "status_code": 0, "payload": {"status": "unavailable"}}
        try:
            response = requests.get(
                f"{self.host.rstrip('/')}{path}",
                timeout=10,
                verify=self.verify,
                headers={"Accept": "application/json"},
            )
            sample["status_code"] = response.status_code
            sample["payload"] = response.json()
        except Exception as exc:
            sample["payload"] = {"status": "unavailable", "error": str(exc)}

        bucket.append(sample)
        with target_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

        if not ready_endpoint or self.stop_condition:
            return

        payload = dict(sample.get("payload") or {})
        metrics = dict(payload.get("metrics") or {})
        pending = dict(payload.get("pending") or {})
        queue_depth = int(payload.get("queue_depth") or metrics.get("queue_depth") or 0)
        pending_chat_p1 = int(pending.get("chat:p1") or 0)
        status = str(payload.get("status") or "")

        if queue_depth > self.queue_runaway_threshold or pending_chat_p1 > self.queue_runaway_threshold:
            self.stop_condition = "health_queue_runaway"
            self.stop_event.set()
            return

        if status != "ready":
            if self._not_ready_since is None:
                self._not_ready_since = time.time()
            elif time.time() - self._not_ready_since >= self.not_ready_grace_seconds:
                self.stop_condition = "health_not_ready_too_long"
                self.stop_event.set()
        else:
            self._not_ready_since = None

from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .profiles import BenchmarkProfile


@dataclass(frozen=True)
class RequestResult:
    user_index: int
    thread_id: str
    start_ms: int
    end_ms: int | None
    latency_ms: int | None
    http_status: int | None
    job_id: str = ""
    completed: bool = False
    timed_out: bool = False
    auth_failed: bool = False
    rejected_429: bool = False
    server_error: bool = False
    incomplete_sse: bool = False
    cancelled: bool = False
    error_message: str = ""
    final_text: str = ""

    @property
    def final_text_short(self) -> str:
        return shorten_text(self.final_text)

    def to_csv_row(self) -> dict[str, object]:
        payload = asdict(self)
        payload["final_text_short"] = self.final_text_short
        return payload


def shorten_text(value: str, max_chars: int = 120) -> str:
    text = (value or "").strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def percentile(values: Iterable[int | float], percent: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percent / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def build_wait_rows(results: Iterable[RequestResult]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in sorted(results, key=lambda result: result.user_index):
        rows.append(
            {
                "user_index": item.user_index,
                "thread_id": item.thread_id,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms or "",
                "latency_ms": item.latency_ms or "",
                "http_status": item.http_status or "",
                "job_id": item.job_id,
                "completed": item.completed,
                "final_text_short": item.final_text_short,
            }
        )
    return rows


def write_requests_csv(path: Path, results: Iterable[RequestResult]) -> None:
    rows = [item.to_csv_row() for item in sorted(results, key=lambda result: result.user_index)]
    fieldnames = [
        "user_index",
        "thread_id",
        "start_ms",
        "end_ms",
        "latency_ms",
        "http_status",
        "job_id",
        "completed",
        "timed_out",
        "auth_failed",
        "rejected_429",
        "server_error",
        "incomplete_sse",
        "cancelled",
        "error_message",
        "final_text",
        "final_text_short",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_wait_table_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    fieldnames = [
        "user_index",
        "thread_id",
        "start_ms",
        "end_ms",
        "latency_ms",
        "http_status",
        "job_id",
        "completed",
        "final_text_short",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_wait_table_markdown(path: Path, rows: Iterable[dict[str, object]]) -> None:
    row_list = list(rows)
    lines = [
        "| user_index | thread_id | latency_ms | http_status | completed | job_id | final_text_short |",
        "| ---: | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in row_list:
        lines.append(
            "| {user_index} | {thread_id} | {latency_ms} | {http_status} | {completed} | {job_id} | {final_text_short} |".format(
                user_index=row["user_index"],
                thread_id=row["thread_id"],
                latency_ms=row["latency_ms"],
                http_status=row["http_status"],
                completed="yes" if row["completed"] else "no",
                job_id=row["job_id"] or "-",
                final_text_short=(row["final_text_short"] or "").replace("|", "\\|"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_health_metrics(samples: Iterable[dict[str, object]]) -> dict[str, object]:
    max_queue_depth = 0
    max_pending_chat_p1 = 0
    max_active_jobs = 0
    capacity_false_samples = 0
    drain_at_ms: int | None = None
    last_ts_ms = 0

    for sample in samples:
        payload = dict(sample.get("payload") or {})
        metrics = dict(payload.get("metrics") or {})
        pending = dict(payload.get("pending") or {})
        ts_ms = int(sample.get("ts_ms") or 0)
        last_ts_ms = max(last_ts_ms, ts_ms)
        queue_depth = int(payload.get("queue_depth") or metrics.get("queue_depth") or 0)
        pending_chat_p1 = int(pending.get("chat:p1") or 0)
        active_jobs = int(payload.get("active_jobs") or metrics.get("active_jobs") or 0)
        capacity = bool(payload.get("capacity"))

        max_queue_depth = max(max_queue_depth, queue_depth)
        max_pending_chat_p1 = max(max_pending_chat_p1, pending_chat_p1)
        max_active_jobs = max(max_active_jobs, active_jobs)
        if not capacity:
            capacity_false_samples += 1
        if drain_at_ms is None and queue_depth == 0 and pending_chat_p1 == 0 and active_jobs == 0:
            drain_at_ms = ts_ms

    return {
        "max_queue_depth": max_queue_depth,
        "max_pending_chat_p1": max_pending_chat_p1,
        "max_active_jobs": max_active_jobs,
        "capacity_false_samples": capacity_false_samples,
        "drain_at_ms": drain_at_ms,
        "last_ts_ms": last_ts_ms,
    }


def classify_run(
    *,
    successful_requests: int,
    total_requests: int,
    timeout_count: int,
    rejected_429_count: int,
    auth_failure_count: int,
    drained: bool,
    max_queue_depth: int,
    max_pending_chat_p1: int,
    capacity_false_samples: int,
    stop_condition_triggered: str,
) -> str:
    if auth_failure_count > 0 and successful_requests == 0:
        return "auth_blocked"
    if stop_condition_triggered.startswith("health_"):
        return "health_blocked"
    if rejected_429_count > 0 and successful_requests == 0:
        return "rate_limit_blocked"
    if timeout_count > 0 and successful_requests == 0:
        return "timeout_blocked"
    if not drained and (max_queue_depth > 0 or max_pending_chat_p1 > 0):
        return "stuck_jobs_detected"
    if rejected_429_count > 0 and rejected_429_count >= max(1, total_requests // 4):
        return "rate_limit_blocked"
    if timeout_count > 0 and timeout_count >= max(1, total_requests // 4):
        return "timeout_blocked"
    if max_queue_depth > 0 or max_pending_chat_p1 > 0 or capacity_false_samples > 0:
        return "completed_with_queue_pressure"
    return "success"


def build_summary(
    *,
    profile: BenchmarkProfile,
    results: Iterable[RequestResult],
    health_ready_samples: Iterable[dict[str, object]],
    measured_end_ms: int,
    stop_condition_triggered: str = "",
) -> dict[str, object]:
    result_list = sorted(results, key=lambda result: result.user_index)
    health_list = list(health_ready_samples)

    latencies = [item.latency_ms for item in result_list if item.completed and item.latency_ms is not None]
    successful_requests = sum(1 for item in result_list if item.completed)
    timeout_count = sum(1 for item in result_list if item.timed_out)
    rejected_429_count = sum(1 for item in result_list if item.rejected_429)
    auth_failure_count = sum(1 for item in result_list if item.auth_failed)
    failed_requests = len(result_list) - successful_requests

    health_metrics = extract_health_metrics(health_list)
    drain_at_ms = health_metrics["drain_at_ms"]
    drained = bool(drain_at_ms is not None and drain_at_ms >= measured_end_ms)
    drain_seconds = None
    if drain_at_ms is not None and drain_at_ms >= measured_end_ms:
        drain_seconds = round((drain_at_ms - measured_end_ms) / 1000.0, 3)
    elif drain_at_ms is not None and not result_list:
        drain_seconds = 0.0

    first_latency = latencies[0] if latencies else None
    median_latency = statistics.median(latencies) if latencies else None
    last_latency = latencies[-1] if latencies else None

    summary = {
        "profile_name": profile.name,
        "concurrency": profile.concurrency,
        "total_requests": len(result_list),
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "timeout_count": timeout_count,
        "rejected_429_count": rejected_429_count,
        "auth_failure_count": auth_failure_count,
        "p50_latency_ms": round(percentile(latencies, 50), 1) if latencies else None,
        "p95_latency_ms": round(percentile(latencies, 95), 1) if latencies else None,
        "first_user_latency_ms": first_latency,
        "median_user_latency_ms": round(median_latency, 1) if median_latency is not None else None,
        "last_user_latency_ms": last_latency,
        "max_queue_depth": int(health_metrics["max_queue_depth"]),
        "max_pending_chat_p1": int(health_metrics["max_pending_chat_p1"]),
        "max_active_jobs": int(health_metrics["max_active_jobs"]),
        "capacity_false_samples": int(health_metrics["capacity_false_samples"]),
        "drained": drained,
        "drain_seconds": drain_seconds,
        "stop_condition_triggered": stop_condition_triggered or "",
    }
    summary["final_classification"] = classify_run(
        successful_requests=successful_requests,
        total_requests=len(result_list),
        timeout_count=timeout_count,
        rejected_429_count=rejected_429_count,
        auth_failure_count=auth_failure_count,
        drained=drained,
        max_queue_depth=summary["max_queue_depth"],
        max_pending_chat_p1=summary["max_pending_chat_p1"],
        capacity_false_samples=summary["capacity_false_samples"],
        stop_condition_triggered=summary["stop_condition_triggered"],
    )
    return summary


def write_summary_json(path: Path, summary: dict[str, object]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

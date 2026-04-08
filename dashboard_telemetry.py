import time
from typing import Any, Dict, Iterable, Optional

from config import settings

HISTORY_RANGE_SECONDS: dict[str, int] = {
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
}
HISTORY_RANGE_LABELS: dict[str, str] = {
    "1h": "1 час",
    "6h": "6 часов",
    "24h": "24 часа",
}
HISTORY_BUCKET_SECONDS: dict[str, int] = {
    "1h": 15,
    "6h": 60,
    "24h": 300,
}


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> Optional[float]:
    items = [float(value) for value in values]
    if not items:
        return None
    return round(sum(items) / len(items), 2)


def _sum_optional(values: Iterable[int]) -> Optional[int]:
    items = [int(value) for value in values]
    if not items:
        return None
    return sum(items)


def _iso_timestamp(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _reported_targets(summary: Dict[str, Any]) -> list[Dict[str, Any]]:
    targets = summary.get("target_rows")
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, dict) and target.get("status") != "stale"]


def sanitize_dashboard_live_sample(sample: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(sample, dict):
        return None
    return {key: value for key, value in sample.items() if not str(key).startswith("_")}


def build_dashboard_event(
    *,
    timestamp: Optional[int] = None,
    severity: str,
    source: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event_ts = int(timestamp or time.time())
    return {
        "timestamp": event_ts,
        "timestamp_iso": _iso_timestamp(event_ts),
        "severity": severity,
        "source": source,
        "message": message,
        "context": dict(context or {}),
    }


def _network_rate_from_targets(
    targets: list[Dict[str, Any]],
    previous_sample: Optional[Dict[str, Any]],
    now_ts: int,
) -> tuple[Optional[float], Optional[float], str, dict[str, dict[str, int]]]:
    current_counters: dict[str, dict[str, int]] = {}
    for target in targets:
        target_id = str(target.get("target_id") or "").strip()
        rx_value = _safe_int(target.get("network_rx_bytes"))
        tx_value = _safe_int(target.get("network_tx_bytes"))
        if not target_id or rx_value is None or tx_value is None:
            continue
        current_counters[target_id] = {"rx": max(0, rx_value), "tx": max(0, tx_value)}

    if not current_counters:
        return None, None, "unavailable", {}

    previous_counters = {}
    if isinstance(previous_sample, dict):
        previous_counters = dict(previous_sample.get("_network_counters") or {})
    previous_ts = _safe_int((previous_sample or {}).get("captured_at"))
    delta_seconds = max(0.0, float(now_ts - previous_ts)) if previous_ts is not None else 0.0
    if delta_seconds <= 0.0 or not previous_counters:
        return None, None, "warming_up", current_counters

    total_rx_delta = 0
    total_tx_delta = 0
    matched_targets = 0
    for target_id, counters in current_counters.items():
        previous = previous_counters.get(target_id)
        if not isinstance(previous, dict):
            continue
        previous_rx = _safe_int(previous.get("rx"))
        previous_tx = _safe_int(previous.get("tx"))
        if previous_rx is None or previous_tx is None:
            continue
        rx_delta = counters["rx"] - previous_rx
        tx_delta = counters["tx"] - previous_tx
        if rx_delta < 0 or tx_delta < 0:
            continue
        matched_targets += 1
        total_rx_delta += rx_delta
        total_tx_delta += tx_delta

    if matched_targets <= 0:
        return None, None, "warming_up", current_counters
    return (
        round(total_rx_delta / delta_seconds, 2),
        round(total_tx_delta / delta_seconds, 2),
        "reported",
        current_counters,
    )


def build_dashboard_live_sample(
    summary: Dict[str, Any],
    *,
    previous_sample: Optional[Dict[str, Any]] = None,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    timestamp = int(now_ts or time.time())
    targets = _reported_targets(summary)

    cpu_values = [
        value
        for value in (_safe_float(target.get("cpu_percent")) for target in targets)
        if value is not None
    ]
    ram_total_values = [
        value
        for value in (_safe_int(target.get("ram_total_mb")) for target in targets)
        if value is not None and value > 0
    ]
    ram_free_values = [
        value
        for value in (_safe_int(target.get("ram_free_mb")) for target in targets)
        if value is not None and value >= 0
    ]
    gpu_targets = [
        target
        for target in targets
        if str(target.get("target_kind") or "").strip().lower() == "gpu"
        or (_safe_int(target.get("vram_total_mb")) or 0) > 0
    ]
    gpu_util_values = [
        value
        for value in (_safe_float(target.get("gpu_utilization")) for target in gpu_targets)
        if value is not None
    ]
    gpu_temp_values = [
        value
        for value in (_safe_float(target.get("gpu_temperature_c")) for target in gpu_targets)
        if value is not None and value > 0
    ]
    vram_total_values = [
        value
        for value in (_safe_int(target.get("vram_total_mb")) for target in gpu_targets)
        if value is not None and value > 0
    ]
    vram_free_values = [
        value
        for value in (_safe_int(target.get("vram_free_mb")) for target in gpu_targets)
        if value is not None and value >= 0
    ]
    network_rx, network_tx, network_availability, network_counters = _network_rate_from_targets(
        targets,
        previous_sample,
        timestamp,
    )

    ram_total_mb = _sum_optional(ram_total_values)
    ram_free_mb = _sum_optional(ram_free_values)
    vram_total_mb = _sum_optional(vram_total_values)
    vram_free_mb = _sum_optional(vram_free_values)
    active_models = sorted({str(item).strip() for item in summary.get("active_models") or [] if str(item).strip()})

    return {
        "captured_at": timestamp,
        "captured_at_iso": _iso_timestamp(timestamp),
        "sampling_interval_seconds": max(2, int(settings.ADMIN_DASHBOARD_TELEMETRY_INTERVAL_SECONDS)),
        "telemetry_scope": "target heartbeat runtime telemetry",
        "source_last_refresh": summary.get("last_refresh"),
        "cpu_percent": _mean(cpu_values),
        "cpu_availability": "reported" if cpu_values else "unavailable",
        "ram_total_mb": ram_total_mb,
        "ram_free_mb": ram_free_mb,
        "ram_used_mb": max(0, ram_total_mb - ram_free_mb) if ram_total_mb is not None and ram_free_mb is not None else None,
        "ram_availability": "reported" if ram_total_mb is not None and ram_free_mb is not None else "unavailable",
        "gpu_available": bool(gpu_targets),
        "gpu_utilization_percent": _mean(gpu_util_values),
        "gpu_temperature_c": _mean(gpu_temp_values),
        "gpu_availability": "reported" if gpu_util_values or vram_total_values else ("unavailable" if gpu_targets else "not_configured"),
        "vram_total_mb": vram_total_mb,
        "vram_free_mb": vram_free_mb,
        "vram_used_mb": max(0, vram_total_mb - vram_free_mb) if vram_total_mb is not None and vram_free_mb is not None else None,
        "network_rx_bytes_per_sec": network_rx,
        "network_tx_bytes_per_sec": network_tx,
        "network_availability": network_availability,
        "network_scope": "target runtime namespace counters",
        "queue_depth": max(0, int(summary.get("queue_depth") or 0)),
        "chat_backlog": max(0, int(summary.get("chat_backlog") or 0)),
        "parser_backlog": max(0, int(summary.get("parser_backlog") or 0)),
        "active_jobs": max(0, int(summary.get("active_jobs") or 0)),
        "workers_total": max(0, int(summary.get("workers_total") or 0)),
        "workers_working": max(0, int(summary.get("workers_working") or 0)),
        "targets": max(0, int(summary.get("targets") or len(targets) or 0)),
        "capacity": bool(summary.get("capacity")),
        "overall_status": str(summary.get("overall_status") or ""),
        "readiness_status": str(summary.get("readiness_status") or ""),
        "health_status": str(summary.get("health_status") or ""),
        "scheduler_status": str(summary.get("scheduler_status") or ""),
        "active_models": active_models,
        "active_models_count": len(active_models),
        "warnings": list(summary.get("warnings") or []),
        "_network_counters": network_counters,
    }


def build_dashboard_events(
    previous_sample: Optional[Dict[str, Any]],
    current_sample: Dict[str, Any],
) -> list[Dict[str, Any]]:
    if not isinstance(previous_sample, dict):
        return []

    events: list[Dict[str, Any]] = []
    timestamp = int(current_sample.get("captured_at") or time.time())

    if previous_sample.get("readiness_status") != current_sample.get("readiness_status"):
        ready = current_sample.get("readiness_status") == "ready"
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info" if ready else "warn",
                source="readiness",
                message="Readiness restored" if ready else "Readiness changed to not_ready",
                context={"status": current_sample.get("readiness_status")},
            )
        )

    if previous_sample.get("scheduler_status") != current_sample.get("scheduler_status"):
        scheduler_healthy = current_sample.get("scheduler_status") == "healthy"
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info" if scheduler_healthy else "error",
                source="scheduler",
                message="Scheduler heartbeat restored" if scheduler_healthy else "Scheduler heartbeat became unavailable",
                context={"status": current_sample.get("scheduler_status")},
            )
        )

    previous_queue = int(previous_sample.get("queue_depth") or 0)
    current_queue = int(current_sample.get("queue_depth") or 0)
    queue_threshold = max(1, int(settings.ADMIN_DASHBOARD_QUEUE_DEPTH_WARN_THRESHOLD))
    if previous_queue < queue_threshold <= current_queue:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="warn",
                source="queue",
                message="Queue depth crossed warning threshold",
                context={"queue_depth": current_queue, "threshold": queue_threshold},
            )
        )
    elif previous_queue >= queue_threshold > current_queue:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info",
                source="queue",
                message="Queue depth returned below warning threshold",
                context={"queue_depth": current_queue, "threshold": queue_threshold},
            )
        )

    previous_chat_backlog = int(previous_sample.get("chat_backlog") or 0)
    current_chat_backlog = int(current_sample.get("chat_backlog") or 0)
    chat_threshold = max(1, int(settings.ADMIN_DASHBOARD_CHAT_BACKLOG_WARN_THRESHOLD))
    if previous_chat_backlog < chat_threshold <= current_chat_backlog:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="warn",
                source="chat_backlog",
                message="Chat backlog spike detected",
                context={"chat_backlog": current_chat_backlog, "threshold": chat_threshold},
            )
        )
    elif previous_chat_backlog >= chat_threshold > current_chat_backlog:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info",
                source="chat_backlog",
                message="Chat backlog returned below warning threshold",
                context={"chat_backlog": current_chat_backlog, "threshold": chat_threshold},
            )
        )

    previous_parser_backlog = int(previous_sample.get("parser_backlog") or 0)
    current_parser_backlog = int(current_sample.get("parser_backlog") or 0)
    parser_threshold = max(1, int(settings.ADMIN_DASHBOARD_PARSER_BACKLOG_WARN_THRESHOLD))
    if previous_parser_backlog < parser_threshold <= current_parser_backlog:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="warn",
                source="parser_backlog",
                message="Parser backlog spike detected",
                context={"parser_backlog": current_parser_backlog, "threshold": parser_threshold},
            )
        )
    elif previous_parser_backlog >= parser_threshold > current_parser_backlog:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info",
                source="parser_backlog",
                message="Parser backlog returned below warning threshold",
                context={"parser_backlog": current_parser_backlog, "threshold": parser_threshold},
            )
        )

    if bool(previous_sample.get("capacity")) != bool(current_sample.get("capacity")):
        capacity_ok = bool(current_sample.get("capacity"))
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info" if capacity_ok else "warn",
                source="capacity",
                message="Chat capacity restored" if capacity_ok else "Chat capacity is unavailable",
                context={"capacity": capacity_ok},
            )
        )

    if int(previous_sample.get("workers_total") or 0) != int(current_sample.get("workers_total") or 0):
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info",
                source="workers",
                message="Worker count changed",
                context={
                    "previous": int(previous_sample.get("workers_total") or 0),
                    "current": int(current_sample.get("workers_total") or 0),
                },
            )
        )

    previous_gpu = previous_sample.get("gpu_availability") == "reported"
    current_gpu = current_sample.get("gpu_availability") == "reported"
    if previous_gpu != current_gpu:
        events.append(
            build_dashboard_event(
                timestamp=timestamp,
                severity="info" if current_gpu else "warn",
                source="gpu",
                message="GPU telemetry restored" if current_gpu else "GPU telemetry unavailable",
                context={"availability": current_sample.get("gpu_availability")},
            )
        )

    return events


def normalize_history_range(range_key: Optional[str]) -> str:
    normalized = str(range_key or "24h").strip().lower()
    return normalized if normalized in HISTORY_RANGE_SECONDS else "24h"


def build_dashboard_history_payload(
    samples: list[Dict[str, Any]],
    *,
    range_key: Optional[str],
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    normalized_range = normalize_history_range(range_key)
    range_seconds = HISTORY_RANGE_SECONDS[normalized_range]
    bucket_seconds = HISTORY_BUCKET_SECONDS[normalized_range]
    current_ts = int(now_ts or time.time())
    oldest_allowed = current_ts - range_seconds
    relevant_samples = [
        sanitize_dashboard_live_sample(sample)
        for sample in samples
        if isinstance(sample, dict) and int(sample.get("captured_at") or 0) >= oldest_allowed
    ]
    relevant_samples = [sample for sample in relevant_samples if sample is not None]
    relevant_samples.sort(key=lambda sample: int(sample.get("captured_at") or 0))

    buckets: dict[int, Dict[str, Any]] = {}
    for sample in relevant_samples:
        bucket_start = int(sample.get("captured_at") or 0) // bucket_seconds
        buckets[bucket_start] = sample

    points = [buckets[key] for key in sorted(buckets)]
    latest = sanitize_dashboard_live_sample(relevant_samples[-1]) if relevant_samples else None
    snapshot = sanitize_dashboard_live_sample(points[-1]) if points else None
    return {
        "range": normalized_range,
        "range_label": HISTORY_RANGE_LABELS[normalized_range],
        "bucket_seconds": bucket_seconds,
        "point_count": len(points),
        "points": points,
        "latest": latest,
        "snapshot": snapshot,
    }

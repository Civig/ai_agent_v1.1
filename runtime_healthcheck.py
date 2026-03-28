import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

import redis


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_timeout=env_float("REDIS_SOCKET_TIMEOUT_SECONDS", 5.0),
        socket_connect_timeout=env_float("REDIS_CONNECT_TIMEOUT_SECONDS", 5.0),
        health_check_interval=env_int("REDIS_HEALTHCHECK_INTERVAL_SECONDS", 15),
        retry_on_timeout=os.getenv("REDIS_RETRY_ON_TIMEOUT", "true").lower() == "true",
    )


def assert_pid1_contains(expected: str) -> None:
    with open("/proc/1/cmdline", "rb") as handle:
        cmdline = handle.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
    if expected not in cmdline:
        raise RuntimeError(f"pid1 does not look like {expected}: {cmdline}")


def check_http(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"unexpected HTTP status {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"http check failed: {exc}") from exc


def check_scheduler() -> None:
    assert_pid1_contains("scheduler.py")
    client = redis_client()
    payload_raw = client.get("llm:scheduler:heartbeat")
    if not payload_raw:
        raise RuntimeError("missing scheduler heartbeat")
    payload = json.loads(payload_raw)
    last_seen = int(payload.get("last_seen") or 0)
    ttl = env_int("SCHEDULER_HEARTBEAT_TTL_SECONDS", 15)
    if max(0, int(time.time()) - last_seen) > ttl:
        raise RuntimeError("stale scheduler heartbeat")


def check_worker() -> None:
    assert_pid1_contains("worker.py")
    hostname = socket.gethostname()
    worker_pool = os.getenv("WORKER_POOL", "chat")
    worker_id = f"{hostname}:1:{worker_pool}"
    client = redis_client()
    worker_raw = client.get(f"llm:worker:{worker_id}")
    if not worker_raw:
        raise RuntimeError("missing worker heartbeat")
    worker = json.loads(worker_raw)
    ttl = env_int("WORKER_HEARTBEAT_TTL_SECONDS", 15)
    last_seen = int(worker.get("last_seen") or 0)
    if max(0, int(time.time()) - last_seen) > ttl:
        raise RuntimeError("stale worker heartbeat")
    target_id = os.getenv("WORKER_TARGET_ID", "ollama-main")
    target_raw = client.get(f"llm:target:{target_id}")
    if not target_raw:
        raise RuntimeError("missing target heartbeat")


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if mode == "app":
        assert_pid1_contains("uvicorn")
        check_http("http://127.0.0.1:8000/health/live")
        return 0
    if mode == "scheduler":
        check_scheduler()
        return 0
    if mode == "worker":
        check_worker()
        return 0
    raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())

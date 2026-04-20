#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.smoke.smoke_common import (  # noqa: E402
    REPO_ROOT,
    append_jsonl,
    build_load_summary,
    create_artifact_dir,
    load_cases,
    read_json,
    write_dicts_csv,
    write_json,
)
from scripts.smoke.smoke_runner import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_TIMEOUT_SECONDS,
    SmokeHttpClient,
    build_case_result,
    build_exception_result,
    resolve_credentials,
)


def load_profile(name: str) -> dict[str, Any]:
    profiles = read_json(REPO_ROOT / "tests/smoke/specs/load_profiles.json")["profiles"]
    if name not in profiles:
        raise KeyError(f"Unknown load profile: {name}")
    return {"name": name, **profiles[name]}


def output_dir_for(args: argparse.Namespace) -> Path:
    if args.output_dir:
        path = Path(args.output_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    return create_artifact_dir(REPO_ROOT / "artifacts" / "load", label=f"chat-{args.profile}")


def build_client(args: argparse.Namespace) -> SmokeHttpClient:
    username, password = resolve_credentials(args)
    client = SmokeHttpClient(base_url=args.host, insecure=args.insecure, timeout_seconds=args.timeout_seconds)
    client.login(username=username, password=password)
    client.get_models()
    return client


def run_request(
    *,
    args: argparse.Namespace,
    case: dict[str, Any],
    worker_index: int,
    request_index: int,
    output_dir: Path,
    client: SmokeHttpClient | None = None,
    cold: bool = False,
) -> dict[str, Any]:
    active_client = client or build_client(args)
    thread_id = f"load-chat-{int(time.time())}-{worker_index:02d}-{request_index:03d}"
    started = time.perf_counter()
    try:
        stream = active_client.post_chat_sse(
            prompt=str(case["prompt"]),
            thread_id=thread_id,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        )
        latency_ms = int(round((time.perf_counter() - started) * 1000))
        result = build_case_result(case=case, kind="chat-load", stream=stream, latency_ms=latency_ms, thread_id=thread_id)
    except Exception as exc:
        latency_ms = int(round((time.perf_counter() - started) * 1000))
        result = build_exception_result(case=case, kind="chat-load", error=str(exc), latency_ms=latency_ms, thread_id=thread_id)

    result["worker_index"] = worker_index
    result["request_index"] = request_index
    result["cold"] = cold
    raw_lines = result.pop("_raw_lines", [])
    events = result.pop("_events", [])
    raw_path = output_dir / "raw_sse" / f"{request_index:03d}-{case['id']}.sse"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("".join(raw_lines), encoding="utf-8")
    write_json(output_dir / "events" / f"{request_index:03d}-{case['id']}.json", events)
    return result


def run_worker(
    *,
    args: argparse.Namespace,
    worker_index: int,
    tasks: list[tuple[dict[str, Any], int]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    client = build_client(args)
    rows: list[dict[str, Any]] = []
    for case, request_index in tasks:
        rows.append(
            run_request(
                args=args,
                case=case,
                worker_index=worker_index,
                request_index=request_index,
                output_dir=output_dir,
                client=client,
            )
        )
    return rows


def execute(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    output_dir = output_dir_for(args)
    timeout_seconds = int(args.timeout_seconds or profile.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    args.timeout_seconds = timeout_seconds
    cases = load_cases(args.spec)
    write_json(output_dir / "plan.json", {"profile": profile, "host": args.host, "spec": str(args.spec), "timeout_seconds": timeout_seconds})

    results: list[dict[str, Any]] = []
    if args.profile == "warm_cold":
        cold_case = cases[0]
        cold_result = run_request(args=args, case=cold_case, worker_index=1, request_index=1, output_dir=output_dir, cold=True)
        results.append(cold_result)
        time.sleep(float(profile.get("quiet_seconds_after_cold") or 0))
        total_requests = int(profile["warm_chat_requests"])
        offset = 2
    else:
        total_requests = int(profile["chat_requests"])
        offset = 1

    concurrency = max(1, int(profile["concurrency"]))
    tasks_by_worker: dict[int, list[tuple[dict[str, Any], int]]] = {worker: [] for worker in range(1, concurrency + 1)}
    for index in range(total_requests):
        case = cases[index % len(cases)]
        request_index = offset + index
        worker_index = (index % concurrency) + 1
        tasks_by_worker[worker_index].append((case, request_index))

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                run_worker,
                args=args,
                worker_index=worker_index,
                tasks=worker_tasks,
                output_dir=output_dir,
            )
            for worker_index, worker_tasks in tasks_by_worker.items()
            if worker_tasks
        ]
        for future in as_completed(futures):
            results.extend(future.result())

    results = sorted(results, key=lambda row: int(row["request_index"]))
    results_path = output_dir / "results.jsonl"
    if results_path.exists():
        results_path.unlink()
    for result in results:
        append_jsonl(results_path, result)
    write_dicts_csv(
        output_dir / "results.csv",
        results,
        [
            "request_index",
            "worker_index",
            "id",
            "kind",
            "expected_status",
            "actual_status",
            "passed",
            "http_status",
            "latency_ms",
            "job_id",
            "completed",
            "error",
            "response_text",
            "cold",
        ],
    )
    summary = build_load_summary(results, profile=profile)
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_requests"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight live chat load profiles.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--profile", choices=("light", "medium", "warm_cold"), default="light")
    parser.add_argument("--output-dir")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--password-file")
    parser.add_argument("--spec", default=str(REPO_ROOT / "tests/smoke/specs/chat_cases.json"))
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--insecure", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except Exception as exc:
        print(f"CHAT_LOAD_FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

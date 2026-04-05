from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.load_benchmark.health_sampler import HealthSampler
    from tests.load_benchmark.profiles import BenchmarkProfile, get_profile, load_profiles
    from tests.load_benchmark.reporting import (
        RequestResult,
        build_summary,
        build_wait_rows,
        write_requests_csv,
        write_summary_json,
        write_wait_table_csv,
        write_wait_table_markdown,
    )
    from tests.load_benchmark.session import (
        build_multi_session_pool,
        build_shared_session_pool,
        parse_user_file,
    )
    from tests.load_benchmark.sse_parser import iter_sse_events, summarize_sse_events
else:
    from .health_sampler import HealthSampler
    from .profiles import BenchmarkProfile, get_profile, load_profiles
    from .reporting import (
        RequestResult,
        build_summary,
        build_wait_rows,
        write_requests_csv,
        write_summary_json,
        write_wait_table_csv,
        write_wait_table_markdown,
    )
    from .session import build_multi_session_pool, build_shared_session_pool, parse_user_file
    from .sse_parser import iter_sse_events, summarize_sse_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reusable live load benchmark harness for Corporate AI Assistant.",
    )
    parser.add_argument("--host", required=True, help="Application base URL, e.g. https://127.0.0.1")
    parser.add_argument("--profile", required=True, choices=tuple(load_profiles().keys()))
    parser.add_argument("--output-dir", required=True, help="Directory for benchmark artifacts")
    parser.add_argument("--username", help="Shared-session login username")
    parser.add_argument("--password", help="Shared-session login password")
    parser.add_argument("--user-file", help="Optional username:password list for multi-session mode")
    parser.add_argument("--mode", required=True, choices=("shared-session", "multi-session"))
    parser.add_argument("--ramp-up-seconds", type=float, default=None)
    parser.add_argument("--max-time-seconds", type=int, default=None)
    parser.add_argument("--prompt", default="Ответь ровно словом OK.")
    parser.add_argument("--warmup", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--quiet-window-seconds", type=int, default=None)
    parser.add_argument("--health-sample-seconds", type=float, default=5.0)
    parser.add_argument("--drain-timeout-seconds", type=int, default=180)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "shared-session" and (not args.username or not args.password):
        parser.error("--username and --password are required in shared-session mode")
    if args.mode == "multi-session" and not args.user_file:
        parser.error("--user-file is required in multi-session mode")
    return args


def setup_logging(output_dir: Path) -> logging.Logger:
    logger = logging.getLogger("load-benchmark")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(output_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def build_run_plan(args: argparse.Namespace, profile: BenchmarkProfile) -> dict[str, object]:
    return {
        "profile_name": profile.name,
        "concurrency": profile.concurrency,
        "mode": args.mode,
        "ramp_up_seconds": profile.default_ramp_up_seconds if args.ramp_up_seconds is None else args.ramp_up_seconds,
        "max_time_seconds": profile.default_max_time_seconds if args.max_time_seconds is None else args.max_time_seconds,
        "warmup": profile.default_warmup if args.warmup is None else args.warmup,
        "quiet_window_seconds": (
            profile.default_quiet_window_seconds
            if args.quiet_window_seconds is None
            else args.quiet_window_seconds
        ),
        "prompt": args.prompt,
        "verify": not args.insecure,
        "health_sample_seconds": args.health_sample_seconds,
        "drain_timeout_seconds": args.drain_timeout_seconds,
    }


def run_chat_request(
    *,
    host: str,
    snapshot,
    user_index: int,
    prompt: str,
    max_time_seconds: int,
    output_dir: Path,
    verify: bool,
) -> RequestResult:
    session = snapshot.build_session()
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "X-CSRF-Token": snapshot.csrf_token,
    }
    thread_id = f"bench-{user_index:03d}"
    start_ms = int(time.time() * 1000)
    raw_path = output_dir / "raw_sse"
    raw_path.mkdir(parents=True, exist_ok=True)
    sse_file = raw_path / f"{thread_id}.sse"

    try:
        response = session.post(
            f"{host.rstrip('/')}/api/chat",
            json={"prompt": prompt, "thread_id": thread_id},
            headers=headers,
            stream=True,
            timeout=(10, max_time_seconds),
            verify=verify,
        )
    except requests.Timeout:
        end_ms = int(time.time() * 1000)
        return RequestResult(
            user_index=user_index,
            thread_id=thread_id,
            start_ms=start_ms,
            end_ms=end_ms,
            latency_ms=end_ms - start_ms,
            http_status=None,
            timed_out=True,
            error_message="request_timeout",
        )
    except Exception as exc:
        end_ms = int(time.time() * 1000)
        return RequestResult(
            user_index=user_index,
            thread_id=thread_id,
            start_ms=start_ms,
            end_ms=end_ms,
            latency_ms=end_ms - start_ms,
            http_status=None,
            server_error=True,
            error_message=str(exc),
        )

    if response.status_code != 200:
        end_ms = int(time.time() * 1000)
        error_text = ""
        try:
            payload = response.json()
            error_text = str(payload.get("error") or payload.get("detail") or "")
        except Exception:
            error_text = response.text.strip()
        return RequestResult(
            user_index=user_index,
            thread_id=thread_id,
            start_ms=start_ms,
            end_ms=end_ms,
            latency_ms=end_ms - start_ms,
            http_status=response.status_code,
            auth_failed=response.status_code in {401, 403},
            rejected_429=response.status_code == 429,
            server_error=response.status_code >= 500,
            error_message=error_text or f"http_{response.status_code}",
        )

    raw_lines: list[str] = []
    try:
        for line in response.iter_lines(decode_unicode=True):
            if line is None:
                continue
            raw_lines.append(line)
    except requests.Timeout:
        end_ms = int(time.time() * 1000)
        sse_file.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
        return RequestResult(
            user_index=user_index,
            thread_id=thread_id,
            start_ms=start_ms,
            end_ms=end_ms,
            latency_ms=end_ms - start_ms,
            http_status=200,
            timed_out=True,
            error_message="sse_timeout",
        )

    sse_file.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    end_ms = int(time.time() * 1000)
    summary = summarize_sse_events(iter_sse_events(raw_lines))
    return RequestResult(
        user_index=user_index,
        thread_id=thread_id,
        start_ms=start_ms,
        end_ms=end_ms,
        latency_ms=end_ms - start_ms,
        http_status=200,
        job_id=summary.job_id,
        completed=summary.completed,
        cancelled=summary.cancelled,
        incomplete_sse=summary.incomplete,
        error_message=summary.error or ("incomplete_sse" if summary.incomplete else ""),
        final_text=summary.final_text,
    )


def wait_for_drain(
    *,
    host: str,
    verify: bool,
    timeout_seconds: int,
    logger: logging.Logger,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        ts_ms = int(time.time() * 1000)
        response = requests.get(f"{host.rstrip('/')}/health/ready", timeout=10, verify=verify)
        payload = response.json()
        sample = {"ts_ms": ts_ms, "path": "/health/ready", "status_code": response.status_code, "payload": payload}
        samples.append(sample)
        metrics = dict(payload.get("metrics") or {})
        pending = dict(payload.get("pending") or {})
        queue_depth = int(metrics.get("queue_depth") or 0)
        pending_chat_p1 = int(pending.get("chat:p1") or 0)
        active_jobs = int(payload.get("active_jobs") or 0)
        if queue_depth == 0 and pending_chat_p1 == 0 and active_jobs == 0:
            logger.info("Drain check reached steady state")
            return samples
        time.sleep(2)
    logger.warning("Drain timeout elapsed without full queue drain")
    return samples


def execute_benchmark(args: argparse.Namespace) -> int:
    profile = get_profile(args.profile)
    plan = build_run_plan(args, profile)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(output_dir)
    logger.info("Starting benchmark profile=%s mode=%s output_dir=%s", profile.name, args.mode, output_dir)

    verify = bool(plan["verify"])
    try:
        if args.mode == "shared-session":
            snapshots = build_shared_session_pool(
                host=args.host,
                username=args.username,
                password=args.password,
                verify=verify,
                timeout_seconds=30,
                concurrency=profile.concurrency,
            )
        else:
            snapshots = build_multi_session_pool(
                host=args.host,
                credentials=parse_user_file(Path(args.user_file)),
                verify=verify,
                timeout_seconds=30,
                concurrency=profile.concurrency,
            )
    except RuntimeError as exc:
        logger.error("Session bootstrap failed: %s", exc)
        write_requests_csv(output_dir / "requests.csv", [])
        wait_rows: list[dict[str, object]] = []
        write_wait_table_csv(output_dir / "wait_table.csv", wait_rows)
        write_wait_table_markdown(output_dir / "wait_table.md", wait_rows)
        for file_name in ("health_ready.jsonl", "health.jsonl"):
            (output_dir / file_name).write_text("", encoding="utf-8")
        write_summary_json(
            output_dir / "summary.json",
            {
                "profile_name": profile.name,
                "concurrency": profile.concurrency,
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "timeout_count": 0,
                "rejected_429_count": 0,
                "auth_failure_count": 1,
                "p50_latency_ms": None,
                "p95_latency_ms": None,
                "first_user_latency_ms": None,
                "median_user_latency_ms": None,
                "last_user_latency_ms": None,
                "max_queue_depth": 0,
                "max_pending_chat_p1": 0,
                "max_active_jobs": 0,
                "capacity_false_samples": 0,
                "drained": False,
                "drain_seconds": None,
                "stop_condition_triggered": "auth_session_bootstrap_failed",
                "final_classification": "auth_blocked",
                "error": str(exc),
            },
        )
        return 2

    plan_path = output_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stop_event = None
    measured_end_ms = int(time.time() * 1000)
    sampler = HealthSampler(
        host=args.host,
        output_dir=output_dir,
        verify=verify,
        interval_seconds=float(plan["health_sample_seconds"]),
        queue_runaway_threshold=max(profile.concurrency * 2, 20),
        not_ready_grace_seconds=max(int(plan["max_time_seconds"]), 60),
    )

    if plan["warmup"]:
        logger.info("Running warm-up request")
        warmup = run_chat_request(
            host=args.host,
            snapshot=snapshots[0],
            user_index=0,
            prompt=str(plan["prompt"]),
            max_time_seconds=int(plan["max_time_seconds"]),
            output_dir=output_dir,
            verify=verify,
        )
        logger.info("Warm-up completed http_status=%s completed=%s", warmup.http_status, warmup.completed)
        quiet_window = int(plan["quiet_window_seconds"])
        if quiet_window > 0:
            logger.info("Sleeping quiet window for %ss", quiet_window)
            time.sleep(quiet_window)

    sampler.start()
    results: list[RequestResult] = []
    try:
        with ThreadPoolExecutor(max_workers=profile.concurrency) as executor:
            futures = []
            ramp_up = float(plan["ramp_up_seconds"])
            delay_step = ramp_up / max(profile.concurrency - 1, 1) if profile.concurrency > 1 else 0.0
            for user_index in range(1, profile.concurrency + 1):
                if sampler.stop_event.is_set():
                    logger.warning("Stop condition triggered before launching user_index=%s", user_index)
                    break
                futures.append(
                    executor.submit(
                        run_chat_request,
                        host=args.host,
                        snapshot=snapshots[user_index - 1],
                        user_index=user_index,
                        prompt=str(plan["prompt"]),
                        max_time_seconds=int(plan["max_time_seconds"]),
                        output_dir=output_dir,
                        verify=verify,
                    )
                )
                if delay_step > 0 and user_index != profile.concurrency:
                    time.sleep(delay_step)

            for future in as_completed(futures):
                results.append(future.result())
    finally:
        measured_end_ms = int(time.time() * 1000)
        sampler.stop()

    drain_samples = wait_for_drain(
        host=args.host,
        verify=verify,
        timeout_seconds=int(plan["drain_timeout_seconds"]),
        logger=logger,
    )
    merged_ready_samples = [*sampler.ready_samples, *drain_samples]

    write_requests_csv(output_dir / "requests.csv", results)
    wait_rows = build_wait_rows(results)
    write_wait_table_csv(output_dir / "wait_table.csv", wait_rows)
    write_wait_table_markdown(output_dir / "wait_table.md", wait_rows)

    summary = build_summary(
        profile=profile,
        results=results,
        health_ready_samples=merged_ready_samples,
        measured_end_ms=measured_end_ms,
        stop_condition_triggered=sampler.stop_condition,
    )
    write_summary_json(output_dir / "summary.json", summary)
    logger.info("Benchmark completed classification=%s", summary["final_classification"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return execute_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())

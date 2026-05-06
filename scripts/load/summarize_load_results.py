#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.smoke.smoke_common import build_load_summary, write_dicts_csv, write_json  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def failure_row(*, reason: str, results_path: Path) -> dict[str, Any]:
    return {
        "request_index": 0,
        "worker_index": 0,
        "id": reason,
        "kind": "load-summary",
        "expected_status": "success",
        "actual_status": "failure",
        "passed": False,
        "http_status": None,
        "latency_ms": 0,
        "job_id": "",
        "completed": False,
        "error": f"{reason}: {results_path}",
        "response_text": f"{reason}: {results_path}",
        "failure_reason": reason,
    }


def write_summary_artifacts(
    *,
    input_dir: Path,
    rows: list[dict[str, Any]],
    profile: dict[str, Any],
    failure_reason: str | None = None,
) -> dict[str, Any]:
    summary = build_load_summary(rows, profile=profile)
    summary["status"] = "failed" if failure_reason or summary["failed_requests"] else "passed"
    if failure_reason:
        summary["failure_reason"] = failure_reason
    write_json(input_dir / "summary.json", summary)
    write_dicts_csv(input_dir / "results.csv", rows)
    summary_lines = [
        f"status={summary['status']}",
        f"total_requests={summary['total_requests']}",
        f"successful_requests={summary['successful_requests']}",
        f"failed_requests={summary['failed_requests']}",
        f"p50_latency_ms={summary['p50_latency_ms']}",
        f"p95_latency_ms={summary['p95_latency_ms']}",
        f"max_latency_ms={summary['max_latency_ms']}",
    ]
    if failure_reason:
        summary_lines.append(f"failure_reason={failure_reason}")
    (input_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return summary


def execute(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir).resolve()
    input_dir.mkdir(parents=True, exist_ok=True)
    results_path = Path(args.results_jsonl).resolve() if args.results_jsonl else input_dir / "results.jsonl"
    plan_path = input_dir / "plan.json"
    profile: dict[str, Any] = {}
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        profile = dict(plan.get("profile") or {})

    failure_reason = getattr(args, "failure_reason", None)
    if not results_path.exists():
        failure_reason = failure_reason or "missing_results_jsonl"
        rows = [failure_row(reason=failure_reason, results_path=results_path)]
    else:
        rows = read_jsonl(results_path)

    summary = write_summary_artifacts(
        input_dir=input_dir,
        rows=rows,
        profile=profile,
        failure_reason=failure_reason,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize smoke-kit load result artifacts.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--results-jsonl")
    parser.add_argument("--failure-reason")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

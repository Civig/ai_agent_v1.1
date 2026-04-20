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


def execute(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir).resolve()
    results_path = Path(args.results_jsonl).resolve() if args.results_jsonl else input_dir / "results.jsonl"
    rows = read_jsonl(results_path)
    plan_path = input_dir / "plan.json"
    profile: dict[str, Any] = {}
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        profile = dict(plan.get("profile") or {})
    summary = build_load_summary(rows, profile=profile)
    write_json(input_dir / "summary.json", summary)
    write_dicts_csv(input_dir / "results.csv", rows)
    (input_dir / "summary.txt").write_text(
        "\n".join(
            [
                f"total_requests={summary['total_requests']}",
                f"successful_requests={summary['successful_requests']}",
                f"failed_requests={summary['failed_requests']}",
                f"p50_latency_ms={summary['p50_latency_ms']}",
                f"p95_latency_ms={summary['p95_latency_ms']}",
                f"max_latency_ms={summary['max_latency_ms']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_requests"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize smoke-kit load result artifacts.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--results-jsonl")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

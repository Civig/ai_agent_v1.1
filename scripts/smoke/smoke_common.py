#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SMOKE_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "smoke"
DEFAULT_LOAD_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "load"
OBSERVABILITY_MARKERS = ("job_terminal_observability", "file_parse_observability", "job_queue_observability")
EXPECTED_FILE_CASE_KEYS = {
    "id",
    "file",
    "prompt",
    "must_contain",
    "must_not_contain",
    "expected_status",
    "allowed_fallback",
    "notes",
}


@dataclass(frozen=True)
class SSESummary:
    job_id: str
    completed: bool
    cancelled: bool
    error: str
    final_text: str
    event_count: int
    incomplete: bool


def utc_timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def create_artifact_dir(root: Path | str | None = None, *, label: str = "run") -> Path:
    base = Path(root) if root is not None else DEFAULT_SMOKE_ARTIFACT_ROOT
    path = base / f"{utc_timestamp()}-{safe_identifier(label)}"
    counter = 1
    candidate = path
    while candidate.exists():
        counter += 1
        candidate = base / f"{path.name}-{counter}"
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return normalized or "run"


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path | str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def load_cases(spec_path: Path | str) -> list[dict[str, Any]]:
    payload = read_json(spec_path)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{spec_path} must contain a non-empty cases list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Case #{index} in {spec_path} must be an object")
        case_id = str(item.get("id") or "").strip()
        if not case_id:
            raise ValueError(f"Case #{index} in {spec_path} is missing id")
        if case_id in seen:
            raise ValueError(f"Duplicate case id in {spec_path}: {case_id}")
        seen.add(case_id)
        normalized.append(item)
    return normalized


def validate_file_chat_cases(spec_path: Path | str) -> list[dict[str, Any]]:
    cases = load_cases(spec_path)
    for case in cases:
        missing = sorted(EXPECTED_FILE_CASE_KEYS - set(case.keys()))
        if missing:
            raise ValueError(f"File-chat case {case['id']} is missing keys: {', '.join(missing)}")
        if case["expected_status"] not in {"success", "failure"}:
            raise ValueError(f"File-chat case {case['id']} has invalid expected_status")
        for field in ("must_contain", "must_not_contain"):
            if not isinstance(case.get(field), list):
                raise ValueError(f"File-chat case {case['id']} field {field} must be a list")
    return cases


def resolve_repo_path(path_value: str | Path, *, repo_root: Path | None = None) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return (repo_root or REPO_ROOT) / candidate


def _contains(haystack: str, needle: str) -> bool:
    return str(needle).casefold() in haystack.casefold()


def evaluate_expectations(
    *,
    response_text: str,
    case: dict[str, Any],
    actual_status: str,
) -> dict[str, Any]:
    expected_status = str(case.get("expected_status") or "success")
    must_contain = [str(item) for item in case.get("must_contain") or []]
    must_not_contain = [str(item) for item in case.get("must_not_contain") or []]
    must_contain_any = [str(item) for item in case.get("must_contain_any") or []]

    missing = [item for item in must_contain if not _contains(response_text, item)]
    forbidden = [item for item in must_not_contain if item and _contains(response_text, item)]
    any_missing = bool(must_contain_any) and not any(_contains(response_text, item) for item in must_contain_any)
    status_ok = expected_status == actual_status
    passed = status_ok and not missing and not forbidden and not any_missing
    return {
        "passed": passed,
        "status_ok": status_ok,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "missing": missing,
        "forbidden": forbidden,
        "must_contain_any_missing": any_missing,
    }


def summarize_case_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    passed = sum(1 for row in rows if row.get("passed"))
    failed = len(rows) - passed
    latencies = [int(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    return {
        "total_cases": len(rows),
        "passed": passed,
        "failed": failed,
        "success_rate": round(passed / len(rows), 4) if rows else 0.0,
        "p50_latency_ms": round(percentile(latencies, 50), 1) if latencies else None,
        "p95_latency_ms": round(percentile(latencies, 95), 1) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
    }


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
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def build_load_summary(results: Iterable[dict[str, Any]], *, profile: dict[str, Any]) -> dict[str, Any]:
    rows = list(results)
    latencies = [int(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    successes = sum(1 for row in rows if row.get("passed") or row.get("completed"))
    failures = len(rows) - successes
    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("actual_status") or row.get("status") or "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "profile": profile,
        "total_requests": len(rows),
        "successful_requests": successes,
        "failed_requests": failures,
        "status_counts": status_counts,
        "p50_latency_ms": round(percentile(latencies, 50), 1) if latencies else None,
        "p95_latency_ms": round(percentile(latencies, 95), 1) if latencies else None,
        "min_latency_ms": min(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
    }


def write_dicts_csv(path: Path | str, rows: Iterable[dict[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    row_list = list(rows)
    if fieldnames is None:
        seen: list[str] = []
        for row in row_list:
            for key in row.keys():
                if key not in seen:
                    seen.append(key)
        fieldnames = seen
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(row_list)


def iter_sse_events(lines: Iterable[str | bytes]) -> Iterator[dict[str, Any]]:
    buffer: list[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        stripped = line.rstrip("\r\n")
        if not stripped:
            if buffer:
                yield _parse_sse_block(buffer)
                buffer.clear()
            continue
        if stripped.startswith("data:"):
            buffer.append(stripped[5:].lstrip())
    if buffer:
        yield _parse_sse_block(buffer)


def _parse_sse_block(lines: list[str]) -> dict[str, Any]:
    return json.loads("\n".join(lines))


def summarize_sse_events(events: Iterable[dict[str, Any]]) -> SSESummary:
    job_id = ""
    final_text_parts: list[str] = []
    completed = False
    cancelled = False
    error = ""
    event_count = 0
    for event in events:
        event_count += 1
        if not job_id and isinstance(event.get("job_id"), str):
            job_id = str(event["job_id"])
        token = event.get("token")
        if isinstance(token, str):
            final_text_parts.append(token)
        result = event.get("result")
        if isinstance(result, str) and result:
            final_text_parts = [result]
        event_error = event.get("error")
        if isinstance(event_error, str) and event_error:
            error = event_error
        if event.get("cancelled"):
            cancelled = True
        if event.get("done"):
            completed = True
    return SSESummary(
        job_id=job_id,
        completed=completed and not error and not cancelled,
        cancelled=cancelled,
        error=error,
        final_text="".join(final_text_parts).strip(),
        event_count=event_count,
        incomplete=event_count > 0 and not completed,
    )


def extract_cookie_from_netscape_cookiejar(cookiejar_text: str, name: str) -> str:
    for raw_line in cookiejar_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5] == name:
            return parts[6]
    return ""


def parse_observability_line(line: str) -> dict[str, Any] | None:
    marker = next((item for item in OBSERVABILITY_MARKERS if item in line), "")
    if not marker:
        return None
    payload: dict[str, Any] = {"event": marker, "raw": line.rstrip("\n")}
    for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^ \n\r]+)", line):
        payload[key] = _coerce_observability_value(value)
    if marker in {"job_terminal_observability", "job_queue_observability"}:
        queue_wait = payload.get("queue_wait_ms")
        payload.setdefault("pending_wait_ms", queue_wait if isinstance(queue_wait, int) else "")
        payload.setdefault("admitted_wait_ms", "")
    if marker == "file_parse_observability":
        payload.setdefault("parse_ms", 0)
        payload.setdefault("doc_chars", payload.get("trimmed_doc_chars", 0))
    return payload


def _coerce_observability_value(value: str) -> Any:
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def extract_observability(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        row = parse_observability_line(line)
        if row is not None:
            rows.append(row)
    return rows


def load_env_file(path: Path | str) -> dict[str, str]:
    env: dict[str, str] = {}
    source = Path(path)
    if not source.exists():
        return env
    for raw_line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def read_password_file(path: Path | str) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("secret:"):
            return line.split(":", 1)[1].strip()
        if line.lower().startswith(("username:", "password for", "corporate ai")):
            continue
        if ":" not in line:
            return line
    return ""


def _command_create_artifact_dir(args: argparse.Namespace) -> int:
    print(create_artifact_dir(args.root, label=args.label))
    return 0


def _command_extract_cookie(args: argparse.Namespace) -> int:
    print(extract_cookie_from_netscape_cookiejar(Path(args.cookiejar).read_text(encoding="utf-8"), args.name))
    return 0


def _command_observability(args: argparse.Namespace) -> int:
    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    rows = extract_observability(text)
    if args.jsonl:
        target = Path(args.jsonl)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    if args.csv:
        fields = [
            "event",
            "job_id",
            "username",
            "job_kind",
            "workload_class",
            "target_kind",
            "queue_wait_ms",
            "pending_wait_ms",
            "admitted_wait_ms",
            "inference_ms",
            "total_ms",
            "total_job_ms",
            "receive_ms",
            "parse_ms",
            "doc_chars",
            "original_doc_chars",
            "trimmed_doc_chars",
            "terminal_status",
            "error_type",
            "raw",
        ]
        write_dicts_csv(args.csv, rows, fields)
    print(len(rows))
    return 0


def _command_summarize_results(args: argparse.Namespace) -> int:
    rows = [
        json.loads(line)
        for line in Path(args.input_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = summarize_case_results(rows)
    write_json(args.summary_json, summary)
    if args.summary_txt:
        Path(args.summary_txt).write_text(
            "\n".join(
                [
                    f"total_cases={summary['total_cases']}",
                    f"passed={summary['passed']}",
                    f"failed={summary['failed']}",
                    f"success_rate={summary['success_rate']}",
                    f"p50_latency_ms={summary['p50_latency_ms']}",
                    f"p95_latency_ms={summary['p95_latency_ms']}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared smoke-kit utility helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    artifact = subparsers.add_parser("create-artifact-dir")
    artifact.add_argument("--root", default=str(DEFAULT_SMOKE_ARTIFACT_ROOT))
    artifact.add_argument("--label", default="run")
    artifact.set_defaults(func=_command_create_artifact_dir)

    cookie = subparsers.add_parser("extract-cookie")
    cookie.add_argument("--cookiejar", required=True)
    cookie.add_argument("--name", required=True)
    cookie.set_defaults(func=_command_extract_cookie)

    observability = subparsers.add_parser("observability")
    observability.add_argument("--input", required=True)
    observability.add_argument("--jsonl")
    observability.add_argument("--csv")
    observability.set_defaults(func=_command_observability)

    summary = subparsers.add_parser("summarize-results")
    summary.add_argument("--input-jsonl", required=True)
    summary.add_argument("--summary-json", required=True)
    summary.add_argument("--summary-txt")
    summary.set_defaults(func=_command_summarize_results)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

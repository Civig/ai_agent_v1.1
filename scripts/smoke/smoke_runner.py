#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.smoke.smoke_common import (  # noqa: E402
    REPO_ROOT,
    append_jsonl,
    create_artifact_dir,
    evaluate_expectations,
    iter_sse_events,
    load_cases,
    load_env_file,
    read_password_file,
    resolve_repo_path,
    summarize_case_results,
    summarize_sse_events,
    validate_file_chat_cases,
    write_dicts_csv,
    write_json,
)


DEFAULT_HOST = "https://127.0.0.1"
DEFAULT_TIMEOUT_SECONDS = 240


@dataclass(frozen=True)
class HttpPayload:
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class StreamPayload:
    status: int
    headers: dict[str, str]
    raw_lines: list[str]
    body: bytes


class SmokeHttpClient:
    def __init__(self, *, base_url: str, insecure: bool, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cookie_jar = CookieJar()
        handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPCookieProcessor(self.cookie_jar)]
        if self.base_url.startswith("https://") and insecure:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        self.opener = urllib.request.build_opener(*handlers)

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def cookie(self, name: str) -> str:
        for cookie in self.cookie_jar:
            if cookie.name == name:
                return cookie.value
        return ""

    @property
    def csrf_token(self) -> str:
        return self.cookie("csrf_token")

    def request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> HttpPayload:
        request = urllib.request.Request(
            self.url(path),
            data=data,
            headers=headers or {},
            method=method.upper(),
        )
        try:
            with self.opener.open(request, timeout=timeout_seconds or self.timeout_seconds) as response:
                return HttpPayload(
                    status=int(response.getcode()),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpPayload(status=int(exc.code), headers=dict(exc.headers.items()), body=exc.read())

    def stream(
        self,
        method: str,
        path: str,
        *,
        data: bytes,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> StreamPayload:
        request = urllib.request.Request(self.url(path), data=data, headers=headers, method=method.upper())
        try:
            with self.opener.open(request, timeout=timeout_seconds) as response:
                raw_lines: list[str] = []
                for raw_line in response:
                    raw_lines.append(raw_line.decode("utf-8", errors="replace"))
                return StreamPayload(
                    status=int(response.getcode()),
                    headers=dict(response.headers.items()),
                    raw_lines=raw_lines,
                    body="\n".join(raw_lines).encode("utf-8"),
                )
        except urllib.error.HTTPError as exc:
            return StreamPayload(status=int(exc.code), headers=dict(exc.headers.items()), raw_lines=[], body=exc.read())

    def login(self, *, username: str, password: str) -> dict[str, Any]:
        self.request("GET", "/login")
        payload = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
        login_response = self.request(
            "POST",
            "/login",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if login_response.status >= 400:
            raise RuntimeError(f"login_failed_http_{login_response.status}")
        user_response = self.request("GET", "/api/user", headers={"Accept": "application/json"})
        if user_response.status != 200:
            raise RuntimeError(f"api_user_failed_http_{user_response.status}")
        csrf_token = self.csrf_token
        if not csrf_token:
            raise RuntimeError("csrf_token_cookie_missing")
        return json.loads(user_response.body.decode("utf-8"))

    def get_models(self) -> list[dict[str, Any]]:
        response = self.request("GET", "/api/models", headers={"Accept": "application/json"})
        if response.status != 200:
            detail = decode_error(response.body)
            raise RuntimeError(f"api_models_failed_http_{response.status}: {detail}")
        payload = json.loads(response.body.decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("api_models_empty")
        return payload

    def post_chat_sse(self, *, prompt: str, thread_id: str, model: str | None, timeout_seconds: int) -> StreamPayload:
        payload: dict[str, Any] = {"prompt": prompt, "thread_id": thread_id}
        if model:
            payload["model"] = model
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.stream(
            "POST",
            "/api/chat",
            data=body,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "X-CSRF-Token": self.csrf_token,
            },
            timeout_seconds=timeout_seconds,
        )

    def post_file_chat_sse(
        self,
        *,
        message: str,
        thread_id: str,
        file_path: Path,
        model: str | None,
        timeout_seconds: int,
    ) -> StreamPayload:
        fields = {"message": message, "thread_id": thread_id}
        if model:
            fields["model"] = model
        body, content_type = encode_multipart_form(fields, file_path)
        return self.stream(
            "POST",
            "/api/chat_with_files",
            data=body,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": content_type,
                "X-CSRF-Token": self.csrf_token,
            },
            timeout_seconds=timeout_seconds,
        )


def encode_multipart_form(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----smoke-kit-{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    content_type = guess_content_type(file_path)
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="files"; filename="{file_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def guess_content_type(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def decode_error(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("detail") or payload)[:500]
    return str(payload)[:500]


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    env = load_env_file(REPO_ROOT / ".env")
    username = args.username or os.getenv("SMOKE_USERNAME") or env.get("INSTALL_TEST_USER") or ""
    password = args.password or os.getenv("SMOKE_PASSWORD") or ""
    password_file = args.password_file or os.getenv("SMOKE_PASSWORD_FILE") or ""
    if not password and password_file:
        password = read_password_file(password_file)
    if not username or not password:
        raise RuntimeError(
            "smoke_credentials_missing: set SMOKE_USERNAME and SMOKE_PASSWORD, or SMOKE_PASSWORD_FILE plus INSTALL_TEST_USER"
        )
    return username, password


def prepare_output_dir(args: argparse.Namespace, *, label: str) -> Path:
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
    return create_artifact_dir(REPO_ROOT / "artifacts" / "smoke", label=label)


def bootstrap_session(args: argparse.Namespace, output_dir: Path) -> tuple[SmokeHttpClient, dict[str, Any], list[dict[str, Any]]]:
    username, password = resolve_credentials(args)
    client = SmokeHttpClient(base_url=args.host, insecure=args.insecure, timeout_seconds=args.timeout_seconds)
    user = client.login(username=username, password=password)
    models = client.get_models()
    write_json(
        output_dir / "auth" / "session.json",
        {
            "username": user.get("username"),
            "auth_source": user.get("auth_source"),
            "csrf_cookie_present": bool(client.csrf_token),
            "model_count": len(models),
            "models": [{"key": item.get("key"), "name": item.get("name"), "status": item.get("status")} for item in models],
        },
    )
    return client, user, models


def run_chat(args: argparse.Namespace) -> int:
    output_dir = prepare_output_dir(args, label="chat-smoke")
    client, _, _ = bootstrap_session(args, output_dir)
    cases = load_cases(args.spec)
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
    return run_cases(
        cases=cases,
        output_dir=output_dir,
        kind="chat",
        invoke=lambda case, thread_id: client.post_chat_sse(
            prompt=str(case["prompt"]),
            thread_id=thread_id,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        ),
    )


def run_file_chat(args: argparse.Namespace) -> int:
    output_dir = prepare_output_dir(args, label="file-chat-smoke")
    client, _, _ = bootstrap_session(args, output_dir)
    cases = validate_file_chat_cases(args.spec)
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]

    def invoke(case: dict[str, Any], thread_id: str) -> StreamPayload:
        file_path = resolve_repo_path(str(case["file"]))
        if not file_path.is_file():
            raise RuntimeError(f"fixture_missing: {file_path}")
        return client.post_file_chat_sse(
            message=str(case["prompt"]),
            thread_id=thread_id,
            file_path=file_path,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        )

    return run_cases(cases=cases, output_dir=output_dir, kind="file-chat", invoke=invoke)


def run_cases(
    *,
    cases: list[dict[str, Any]],
    output_dir: Path,
    kind: str,
    invoke,
) -> int:
    if not cases:
        raise RuntimeError("no_cases_selected")
    raw_dir = output_dir / kind / "raw_sse"
    event_dir = output_dir / kind / "events"
    response_dir = output_dir / kind / "responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / kind / "results.jsonl"
    if results_path.exists():
        results_path.unlink()

    results: list[dict[str, Any]] = []
    run_id = int(time.time())
    for index, case in enumerate(cases, start=1):
        case_id = str(case["id"])
        thread_id = f"smoke-{kind}-{run_id}-{index:02d}-{case_id}"[:120]
        started = time.perf_counter()
        try:
            stream = invoke(case, thread_id)
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            result = build_case_result(case=case, kind=kind, stream=stream, latency_ms=latency_ms, thread_id=thread_id)
        except Exception as exc:
            latency_ms = int(round((time.perf_counter() - started) * 1000))
            result = build_exception_result(case=case, kind=kind, error=str(exc), latency_ms=latency_ms, thread_id=thread_id)
        case_safe = str(case_id).replace("/", "_")
        (raw_dir / f"{case_safe}.sse").write_text("".join(result.pop("_raw_lines", [])), encoding="utf-8")
        write_json(event_dir / f"{case_safe}.json", result.pop("_events", []))
        (response_dir / f"{case_safe}.txt").write_text(result.get("response_text") or result.get("error") or "", encoding="utf-8")
        append_jsonl(results_path, result)
        results.append(result)
        print(
            f"{case_id}: {'PASS' if result['passed'] else 'FAIL'} "
            f"status={result['actual_status']} latency_ms={result['latency_ms']} job_id={result.get('job_id') or '-'}"
        )

    write_dicts_csv(
        output_dir / kind / "results.csv",
        results,
        [
            "id",
            "kind",
            "file",
            "expected_status",
            "actual_status",
            "passed",
            "http_status",
            "latency_ms",
            "job_id",
            "completed",
            "cancelled",
            "incomplete",
            "error",
            "missing",
            "forbidden",
            "response_text",
        ],
    )
    summary = summarize_case_results(results)
    write_json(output_dir / kind / "summary.json", summary)
    (output_dir / kind / "summary.txt").write_text(
        "\n".join(
            [
                f"kind={kind}",
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
    return 0 if summary["failed"] == 0 else 1


def build_case_result(
    *,
    case: dict[str, Any],
    kind: str,
    stream: StreamPayload,
    latency_ms: int,
    thread_id: str,
) -> dict[str, Any]:
    if stream.status != 200:
        text = decode_error(stream.body)
        actual_status = "failure"
        expectation = evaluate_expectations(response_text=text, case=case, actual_status=actual_status)
        return {
            "id": case["id"],
            "kind": kind,
            "file": case.get("file", ""),
            "thread_id": thread_id,
            "expected_status": expectation["expected_status"],
            "actual_status": actual_status,
            "passed": expectation["passed"],
            "http_status": stream.status,
            "latency_ms": latency_ms,
            "job_id": "",
            "completed": False,
            "cancelled": False,
            "incomplete": False,
            "error": text,
            "response_text": text,
            "missing": ",".join(expectation["missing"]),
            "forbidden": ",".join(expectation["forbidden"]),
            "_raw_lines": [],
            "_events": [],
        }

    events = list(iter_sse_events(stream.raw_lines))
    summary = summarize_sse_events(events)
    text = summary.error or summary.final_text
    actual_status = "success" if summary.completed else "failure"
    expectation = evaluate_expectations(response_text=text, case=case, actual_status=actual_status)
    return {
        "id": case["id"],
        "kind": kind,
        "file": case.get("file", ""),
        "thread_id": thread_id,
        "expected_status": expectation["expected_status"],
        "actual_status": actual_status,
        "passed": expectation["passed"],
        "http_status": stream.status,
        "latency_ms": latency_ms,
        "job_id": summary.job_id,
        "completed": summary.completed,
        "cancelled": summary.cancelled,
        "incomplete": summary.incomplete,
        "error": summary.error,
        "response_text": summary.final_text or summary.error,
        "missing": ",".join(expectation["missing"]),
        "forbidden": ",".join(expectation["forbidden"]),
        "_raw_lines": stream.raw_lines,
        "_events": events,
    }


def build_exception_result(
    *,
    case: dict[str, Any],
    kind: str,
    error: str,
    latency_ms: int,
    thread_id: str,
) -> dict[str, Any]:
    expectation = evaluate_expectations(response_text=error, case=case, actual_status="failure")
    return {
        "id": case["id"],
        "kind": kind,
        "file": case.get("file", ""),
        "thread_id": thread_id,
        "expected_status": expectation["expected_status"],
        "actual_status": "failure",
        "passed": expectation["passed"],
        "http_status": None,
        "latency_ms": latency_ms,
        "job_id": "",
        "completed": False,
        "cancelled": False,
        "incomplete": False,
        "error": error,
        "response_text": error,
        "missing": ",".join(expectation["missing"]),
        "forbidden": ",".join(expectation["forbidden"]),
        "_raw_lines": [],
        "_events": [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live chat and file-chat smoke cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("chat", "file-chat"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--host", default=os.getenv("SMOKE_BASE_URL", DEFAULT_HOST))
        sub.add_argument("--output-dir")
        sub.add_argument("--username")
        sub.add_argument("--password")
        sub.add_argument("--password-file")
        sub.add_argument("--spec", required=True)
        sub.add_argument("--case-id")
        sub.add_argument("--model")
        sub.add_argument("--timeout-seconds", type=int, default=int(os.getenv("SMOKE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))
        sub.add_argument("--insecure", action="store_true")
        sub.set_defaults(func=run_chat if name == "chat" else run_file_chat)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(f"SMOKE_SETUP_FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

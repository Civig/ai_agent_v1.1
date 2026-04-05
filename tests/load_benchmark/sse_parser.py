from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class SSESummary:
    job_id: str
    completed: bool
    cancelled: bool
    error: str
    final_text: str
    event_count: int
    incomplete: bool


def iter_sse_events(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    buffer: list[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        stripped = line.rstrip("\r\n")
        if not stripped:
            if buffer:
                yield _parse_block(buffer)
                buffer.clear()
            continue
        if stripped.startswith("data:"):
            buffer.append(stripped[5:].lstrip())

    if buffer:
        yield _parse_block(buffer)


def _parse_block(lines: list[str]) -> dict[str, object]:
    payload = "\n".join(lines)
    return json.loads(payload)


def summarize_sse_events(events: Iterable[dict[str, object]]) -> SSESummary:
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
        if isinstance(event.get("error"), str) and event.get("error"):
            error = str(event["error"])
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

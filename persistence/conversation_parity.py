from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .conversation_store import ConversationStore


class ConversationParitySource(Protocol):
    async def list_threads(self, username: str) -> list[dict[str, Any]]:
        ...

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, Any]]:
        ...


PARITY_MATCHED = "matched"
PARITY_MISSING_IN_DB = "missing_in_db"
PARITY_MISSING_IN_SOURCE = "missing_in_source"
PARITY_CONTENT_MISMATCH = "content_mismatch"
PARITY_EMPTY_THREAD = "empty_thread"


@dataclass(frozen=True)
class ConversationThreadParityResult:
    thread_id: str
    status: str
    source_message_count: int
    db_message_count: int


@dataclass(frozen=True)
class ConversationUserParityResult:
    username: str
    matched_threads: tuple[str, ...]
    missing_in_db_threads: tuple[str, ...]
    missing_in_source_threads: tuple[str, ...]
    content_mismatch_threads: tuple[str, ...]
    empty_threads: tuple[str, ...]


async def compare_thread_for_user(
    source_store: ConversationParitySource,
    db_store: ConversationStore,
    username: str,
    thread_id: str,
) -> ConversationThreadParityResult:
    source_messages = await source_store.get_history(username, thread_id=thread_id)
    return compare_history_snapshot_to_store(
        source_messages,
        db_store,
        username,
        thread_id,
    )


def compare_history_snapshot_to_store(
    source_messages: list[dict[str, Any]],
    db_store: ConversationStore,
    username: str,
    thread_id: str,
) -> ConversationThreadParityResult:
    db_messages = db_store.get_messages(username, thread_id)
    return compare_history_snapshot_to_messages(
        source_messages,
        db_messages,
        thread_id,
    )


def compare_history_snapshot_to_messages(
    source_messages: list[dict[str, Any]],
    db_messages: list[Any],
    thread_id: str,
) -> ConversationThreadParityResult:
    source_count = len(source_messages)
    db_count = len(db_messages)

    if source_count == 0 and db_count == 0:
        return ConversationThreadParityResult(
            thread_id=thread_id,
            status=PARITY_EMPTY_THREAD,
            source_message_count=0,
            db_message_count=0,
        )

    if source_count > 0 and db_count == 0:
        return ConversationThreadParityResult(
            thread_id=thread_id,
            status=PARITY_MISSING_IN_DB,
            source_message_count=source_count,
            db_message_count=db_count,
        )

    if source_count == 0 and db_count > 0:
        return ConversationThreadParityResult(
            thread_id=thread_id,
            status=PARITY_MISSING_IN_SOURCE,
            source_message_count=source_count,
            db_message_count=db_count,
        )

    source_snapshot = _normalize_source_messages(source_messages)
    db_snapshot = _normalize_db_messages(db_messages)
    status = PARITY_MATCHED if source_snapshot == db_snapshot else PARITY_CONTENT_MISMATCH
    return ConversationThreadParityResult(
        thread_id=thread_id,
        status=status,
        source_message_count=source_count,
        db_message_count=db_count,
    )


async def compare_all_threads_for_user(
    source_store: ConversationParitySource,
    db_store: ConversationStore,
    username: str,
) -> ConversationUserParityResult:
    source_thread_ids = _extract_source_thread_ids(await source_store.list_threads(username))
    db_thread_ids = {thread.thread_id for thread in db_store.list_threads(username)}
    all_thread_ids = sorted(source_thread_ids | db_thread_ids)

    matched: list[str] = []
    missing_in_db: list[str] = []
    missing_in_source: list[str] = []
    content_mismatch: list[str] = []
    empty_threads: list[str] = []

    for thread_id in all_thread_ids:
        result = await compare_thread_for_user(source_store, db_store, username, thread_id)
        if result.status == PARITY_MATCHED:
            matched.append(thread_id)
        elif result.status == PARITY_MISSING_IN_DB:
            missing_in_db.append(thread_id)
        elif result.status == PARITY_MISSING_IN_SOURCE:
            missing_in_source.append(thread_id)
        elif result.status == PARITY_CONTENT_MISMATCH:
            content_mismatch.append(thread_id)
        elif result.status == PARITY_EMPTY_THREAD:
            empty_threads.append(thread_id)

    return ConversationUserParityResult(
        username=username,
        matched_threads=tuple(matched),
        missing_in_db_threads=tuple(missing_in_db),
        missing_in_source_threads=tuple(missing_in_source),
        content_mismatch_threads=tuple(content_mismatch),
        empty_threads=tuple(empty_threads),
    )


def _extract_source_thread_ids(thread_summaries: list[dict[str, Any]]) -> set[str]:
    thread_ids: set[str] = set()
    for item in thread_summaries:
        thread_id = str(item.get("thread_id") or item.get("id") or "").strip()
        if not thread_id:
            raise ValueError("thread summary must include thread_id or id")
        thread_ids.add(thread_id)
    return thread_ids


def _normalize_source_messages(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for item in messages:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        normalized.append((role, content))
    return normalized


def _normalize_db_messages(messages: list[Any]) -> list[tuple[str, str]]:
    return [(str(item.role).strip(), str(item.content).strip()) for item in messages]

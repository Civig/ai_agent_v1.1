from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .conversation_migration import migrate_thread_from_history
from .conversation_store import ConversationStore


class ConversationHistorySource(Protocol):
    async def list_threads(self, username: str) -> list[dict[str, Any]]:
        ...

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class ConversationThreadMigrationResult:
    thread_id: str
    migrated: bool
    message_count: int
    skipped_empty: bool


@dataclass(frozen=True)
class ConversationUserMigrationResult:
    username: str
    migrated_thread_count: int
    migrated_message_count: int
    skipped_empty_threads: tuple[str, ...]


async def migrate_thread_for_user(
    source_store: ConversationHistorySource,
    db_store: ConversationStore,
    username: str,
    thread_id: str,
) -> ConversationThreadMigrationResult:
    history = await source_store.get_history(username, thread_id=thread_id)
    if not history:
        return ConversationThreadMigrationResult(
            thread_id=thread_id,
            migrated=False,
            message_count=0,
            skipped_empty=True,
        )

    imported = migrate_thread_from_history(db_store, username, thread_id, history)
    return ConversationThreadMigrationResult(
        thread_id=thread_id,
        migrated=True,
        message_count=len(imported),
        skipped_empty=False,
    )


async def migrate_all_threads_for_user(
    source_store: ConversationHistorySource,
    db_store: ConversationStore,
    username: str,
) -> ConversationUserMigrationResult:
    thread_summaries = await source_store.list_threads(username)
    thread_ids: list[str] = []
    seen: set[str] = set()
    for item in thread_summaries:
        thread_id = _extract_thread_id(item)
        if thread_id in seen:
            continue
        seen.add(thread_id)
        thread_ids.append(thread_id)

    migrated_thread_count = 0
    migrated_message_count = 0
    skipped_empty_threads: list[str] = []

    for thread_id in thread_ids:
        result = await migrate_thread_for_user(source_store, db_store, username, thread_id)
        if result.skipped_empty:
            skipped_empty_threads.append(result.thread_id)
            continue
        migrated_thread_count += 1
        migrated_message_count += result.message_count

    return ConversationUserMigrationResult(
        username=username,
        migrated_thread_count=migrated_thread_count,
        migrated_message_count=migrated_message_count,
        skipped_empty_threads=tuple(skipped_empty_threads),
    )


def _extract_thread_id(thread_summary: dict[str, Any]) -> str:
    thread_id = str(thread_summary.get("thread_id") or thread_summary.get("id") or "").strip()
    if not thread_id:
        raise ValueError("thread summary must include thread_id or id")
    return thread_id

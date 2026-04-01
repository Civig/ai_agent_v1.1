from __future__ import annotations

from typing import Mapping, Sequence

from .conversation_store import (
    ConversationMessageRecord,
    ConversationSnapshotMessage,
    ConversationStore,
)


def normalize_history_to_snapshot(
    history_messages: Sequence[Mapping[str, object]],
) -> list[ConversationSnapshotMessage]:
    snapshot: list[ConversationSnapshotMessage] = []
    for item in history_messages:
        if not isinstance(item, Mapping):
            raise TypeError("history messages must be mappings with role/content")
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role:
            raise ValueError("history message role must not be empty")
        if not content:
            raise ValueError("history message content must not be empty")
        snapshot.append(ConversationSnapshotMessage(role=role, content=content))
    return snapshot


def migrate_thread_from_history(
    store: ConversationStore,
    username: str,
    thread_id: str,
    history_messages: Sequence[Mapping[str, object]],
) -> list[ConversationMessageRecord]:
    snapshot = normalize_history_to_snapshot(history_messages)
    return store.import_thread_snapshot(username, thread_id, snapshot)


def migrate_threads_for_user(
    store: ConversationStore,
    username: str,
    thread_histories: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, list[ConversationMessageRecord]]:
    results: dict[str, list[ConversationMessageRecord]] = {}
    for thread_id, history_messages in thread_histories.items():
        results[thread_id] = migrate_thread_from_history(store, username, thread_id, history_messages)
    return results

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .conversation_store import ConversationStore
from .database import (
    ConversationPersistenceRuntime,
    close_conversation_persistence,
    init_conversation_persistence,
    resolve_conversation_persistence_settings,
)


@dataclass(frozen=True)
class ConversationPersistenceCoordinator:
    runtime: ConversationPersistenceRuntime
    store: ConversationStore


def open_conversation_persistence_runtime(
    app_settings: object,
    *,
    bootstrap_schema: Optional[bool] = None,
) -> Optional[ConversationPersistenceCoordinator]:
    resolved = resolve_conversation_persistence_settings(app_settings)
    if not resolved.enabled:
        return None

    create_schema = resolved.bootstrap_schema if bootstrap_schema is None else bootstrap_schema
    runtime = init_conversation_persistence(
        resolved.database_url,
        echo=resolved.echo,
        pool_pre_ping=resolved.pool_pre_ping,
        create_schema=create_schema,
    )
    return ConversationPersistenceCoordinator(
        runtime=runtime,
        store=ConversationStore(runtime.session_factory),
    )


def close_conversation_persistence_runtime(
    coordinator: Optional[ConversationPersistenceCoordinator],
) -> None:
    if coordinator is None:
        return
    close_conversation_persistence(coordinator.runtime)

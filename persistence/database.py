from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from .conversation_models import ConversationBase


@dataclass(frozen=True)
class ConversationPersistenceRuntime:
    engine: Engine
    session_factory: sessionmaker[Session]


def create_persistent_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
) -> Engine:
    normalized_url = (database_url or "").strip()
    if not normalized_url:
        raise ValueError("PERSISTENT_DB_URL must not be empty when persistent DB bootstrap is requested")

    engine_url: URL = make_url(normalized_url)
    return create_engine(
        engine_url,
        echo=echo,
        future=True,
        pool_pre_ping=pool_pre_ping,
    )


def create_persistent_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_conversation_persistence(
    database_url: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
    create_schema: bool = True,
) -> ConversationPersistenceRuntime:
    engine = create_persistent_engine(
        database_url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
    )
    if create_schema:
        ConversationBase.metadata.create_all(engine)
    return ConversationPersistenceRuntime(
        engine=engine,
        session_factory=create_persistent_session_factory(engine),
    )


def close_conversation_persistence(runtime: Optional[ConversationPersistenceRuntime]) -> None:
    if runtime is None:
        return
    runtime.engine.dispose()


def init_conversation_persistence_from_settings(
    app_settings: object,
    *,
    create_schema: bool = True,
) -> Optional[ConversationPersistenceRuntime]:
    if not bool(getattr(app_settings, "PERSISTENT_DB_ENABLED", False)):
        return None

    database_url = str(getattr(app_settings, "PERSISTENT_DB_URL", "") or "").strip()
    echo = bool(getattr(app_settings, "PERSISTENT_DB_ECHO", False))
    pool_pre_ping = bool(getattr(app_settings, "PERSISTENT_DB_POOL_PRE_PING", True))

    return init_conversation_persistence(
        database_url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        create_schema=create_schema,
    )

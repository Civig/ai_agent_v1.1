from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .conversation_models import ConversationMessage, ConversationThread


@dataclass(frozen=True)
class ConversationThreadRecord:
    id: int
    username: str
    thread_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationMessageRecord:
    id: int
    thread_pk: int
    message_index: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class ConversationSnapshotMessage:
    role: str
    content: str


class ConversationStore:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def create_or_get_thread(self, username: str, thread_id: str) -> ConversationThreadRecord:
        normalized_username = username.strip()
        normalized_thread_id = thread_id.strip()
        if not normalized_username:
            raise ValueError("username must not be empty")
        if not normalized_thread_id:
            raise ValueError("thread_id must not be empty")

        with self.session_factory() as session:
            thread = self._find_thread(session, normalized_username, normalized_thread_id)
            if thread is None:
                thread = ConversationThread(username=normalized_username, thread_id=normalized_thread_id)
                session.add(thread)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    thread = self._find_thread(session, normalized_username, normalized_thread_id)
                    if thread is None:
                        raise
                else:
                    session.refresh(thread)
            return self._thread_record(thread)

    def get_thread(self, username: str, thread_id: str) -> Optional[ConversationThreadRecord]:
        with self.session_factory() as session:
            thread = self._find_thread(session, username.strip(), thread_id.strip())
            if thread is None:
                return None
            return self._thread_record(thread)

    def list_threads(self, username: str) -> list[ConversationThreadRecord]:
        normalized_username = username.strip()
        if not normalized_username:
            raise ValueError("username must not be empty")

        with self.session_factory() as session:
            rows = session.scalars(
                select(ConversationThread)
                .where(ConversationThread.username == normalized_username)
                .order_by(ConversationThread.updated_at.desc(), ConversationThread.id.desc())
            ).all()
            return [self._thread_record(row) for row in rows]

    def append_message(self, username: str, thread_id: str, role: str, content: str) -> ConversationMessageRecord:
        normalized_username = username.strip()
        normalized_thread_id = thread_id.strip()
        normalized_role = role.strip()
        if not normalized_username:
            raise ValueError("username must not be empty")
        if not normalized_thread_id:
            raise ValueError("thread_id must not be empty")
        if not normalized_role:
            raise ValueError("role must not be empty")
        if not content:
            raise ValueError("content must not be empty")

        with self.session_factory() as session:
            thread = self._find_thread(session, normalized_username, normalized_thread_id)
            if thread is None:
                thread = ConversationThread(username=normalized_username, thread_id=normalized_thread_id)
                session.add(thread)
                session.flush()

            max_index = session.scalar(
                select(func.max(ConversationMessage.message_index)).where(
                    ConversationMessage.thread_pk == thread.id
                )
            )
            next_index = (max_index if max_index is not None else -1) + 1

            message = ConversationMessage(
                thread_pk=thread.id,
                message_index=next_index,
                role=normalized_role,
                content=content,
            )
            session.add(message)
            thread.updated_at = func.now()
            session.commit()
            session.refresh(thread)
            session.refresh(message)
            return self._message_record(message)

    def get_messages(self, username: str, thread_id: str) -> list[ConversationMessageRecord]:
        with self.session_factory() as session:
            thread = self._find_thread(session, username.strip(), thread_id.strip())
            if thread is None:
                return []

            rows = session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.thread_pk == thread.id)
                .order_by(ConversationMessage.message_index.asc(), ConversationMessage.id.asc())
            ).all()
            return [self._message_record(row) for row in rows]

    def delete_thread_messages(self, username: str, thread_id: str) -> int:
        with self.session_factory() as session:
            thread = self._find_thread(session, username.strip(), thread_id.strip())
            if thread is None:
                return 0

            rows = session.scalars(
                select(ConversationMessage).where(ConversationMessage.thread_pk == thread.id)
            ).all()
            deleted_count = len(rows)
            for row in rows:
                session.delete(row)
            thread.updated_at = func.now()
            session.commit()
            return deleted_count

    def import_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: Sequence[ConversationSnapshotMessage | Mapping[str, object]],
    ) -> list[ConversationMessageRecord]:
        normalized_username = self._require_non_empty(username, "username")
        normalized_thread_id = self._require_non_empty(thread_id, "thread_id")
        snapshot = self._normalize_snapshot_messages(messages)

        with self.session_factory() as session:
            thread = self._find_thread(session, normalized_username, normalized_thread_id)
            if thread is None:
                thread = ConversationThread(username=normalized_username, thread_id=normalized_thread_id)
                session.add(thread)
                session.flush()

            existing_messages = self._load_thread_messages(session, thread.id)
            if self._snapshot_matches_rows(snapshot, existing_messages):
                return [self._message_record(row) for row in existing_messages]

            self._replace_messages(session, thread, snapshot)
            session.commit()
            return [self._message_record(row) for row in self._load_thread_messages(session, thread.id)]

    def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: Sequence[ConversationSnapshotMessage | Mapping[str, object]],
    ) -> list[ConversationMessageRecord]:
        normalized_username = self._require_non_empty(username, "username")
        normalized_thread_id = self._require_non_empty(thread_id, "thread_id")
        snapshot = self._normalize_snapshot_messages(messages)

        with self.session_factory() as session:
            thread = self._find_thread(session, normalized_username, normalized_thread_id)
            if thread is None:
                thread = ConversationThread(username=normalized_username, thread_id=normalized_thread_id)
                session.add(thread)
                session.flush()

            self._replace_messages(session, thread, snapshot)
            session.commit()
            return [self._message_record(row) for row in self._load_thread_messages(session, thread.id)]

    @staticmethod
    def _find_thread(session: Session, username: str, thread_id: str) -> Optional[ConversationThread]:
        if not username or not thread_id:
            return None
        return session.scalar(
            select(ConversationThread).where(
                ConversationThread.username == username,
                ConversationThread.thread_id == thread_id,
            )
        )

    @staticmethod
    def _thread_record(row: ConversationThread) -> ConversationThreadRecord:
        return ConversationThreadRecord(
            id=row.id,
            username=row.username,
            thread_id=row.thread_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _message_record(row: ConversationMessage) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            id=row.id,
            thread_pk=row.thread_pk,
            message_index=row.message_index,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        )

    @staticmethod
    def _require_non_empty(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        return normalized

    @classmethod
    def _normalize_snapshot_messages(
        cls,
        messages: Sequence[ConversationSnapshotMessage | Mapping[str, object]],
    ) -> list[ConversationSnapshotMessage]:
        normalized: list[ConversationSnapshotMessage] = []
        for item in messages:
            if isinstance(item, ConversationSnapshotMessage):
                role = cls._require_non_empty(item.role, "role")
                content = cls._require_non_empty(item.content, "content")
            elif isinstance(item, Mapping):
                role = cls._require_non_empty(str(item.get("role") or ""), "role")
                content = cls._require_non_empty(str(item.get("content") or ""), "content")
            else:
                raise TypeError("snapshot messages must be mappings with role/content or ConversationSnapshotMessage")
            normalized.append(ConversationSnapshotMessage(role=role, content=content))
        return normalized

    @staticmethod
    def _load_thread_messages(session: Session, thread_pk: int) -> list[ConversationMessage]:
        return session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.thread_pk == thread_pk)
            .order_by(ConversationMessage.message_index.asc(), ConversationMessage.id.asc())
        ).all()

    @staticmethod
    def _snapshot_matches_rows(
        snapshot: Sequence[ConversationSnapshotMessage],
        rows: Sequence[ConversationMessage],
    ) -> bool:
        if len(snapshot) != len(rows):
            return False
        return all(
            snapshot_item.role == row.role and snapshot_item.content == row.content
            for snapshot_item, row in zip(snapshot, rows)
        )

    @staticmethod
    def _replace_messages(
        session: Session,
        thread: ConversationThread,
        snapshot: Sequence[ConversationSnapshotMessage],
    ) -> None:
        existing_rows = ConversationStore._load_thread_messages(session, thread.id)
        for row in existing_rows:
            session.delete(row)
        session.flush()

        for index, item in enumerate(snapshot):
            session.add(
                ConversationMessage(
                    thread_pk=thread.id,
                    message_index=index,
                    role=item.role,
                    content=item.content,
                )
            )
        thread.updated_at = func.now()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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

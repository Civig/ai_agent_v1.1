from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ConversationBase(DeclarativeBase):
    pass


class ConversationThread(ConversationBase):
    __tablename__ = "conversation_threads"
    __table_args__ = (
        UniqueConstraint("username", "thread_id", name="uq_conversation_threads_username_thread_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[List["ConversationMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.message_index",
    )


class ConversationMessage(ConversationBase):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("thread_pk", "message_index", name="uq_conversation_messages_thread_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_pk: Mapped[int] = mapped_column(
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    thread: Mapped[ConversationThread] = relationship(back_populates="messages")

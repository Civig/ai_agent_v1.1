from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Optional, Protocol, Sequence

DEFAULT_THREAD_ID = "default"


class ConversationWriteBackend(Protocol):
    async def create_thread(self, username: str, *, thread_id: Optional[str] = None) -> str:
        ...

    async def append_message(
        self,
        username: str,
        role: str,
        content: str,
        *,
        thread_id: Optional[str] = None,
    ) -> None:
        ...

    async def clear_history(
        self,
        username: str,
        *,
        thread_id: Optional[str] = None,
        preserve_thread: bool = True,
    ) -> None:
        ...


class ConversationWriteMirrorStore(Protocol):
    def create_or_get_thread(self, username: str, thread_id: str) -> object:
        ...

    def append_message(self, username: str, thread_id: str, role: str, content: str) -> object:
        ...

    def delete_thread_messages(self, username: str, thread_id: str) -> int:
        ...

    def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> object:
        ...


class RedisConversationWriteCoordinator:
    def __init__(
        self,
        chat_store: ConversationWriteBackend,
        *,
        db_store: Optional[ConversationWriteMirrorStore] = None,
        dual_write_enabled: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self.chat_store = chat_store
        self.db_store = db_store
        self.dual_write_enabled = dual_write_enabled
        self.logger = logger or logging.getLogger(__name__)

    async def ensure_thread(self, username: str, *, thread_id: Optional[str] = None) -> str:
        created_thread_id = await self.chat_store.create_thread(username, thread_id=thread_id)
        await self._mirror_best_effort(
            "ensure_thread",
            username=username,
            thread_id=created_thread_id,
            action=lambda: self.db_store.create_or_get_thread(username, created_thread_id),
        )
        return created_thread_id

    async def append_message(
        self,
        username: str,
        role: str,
        content: str,
        *,
        thread_id: Optional[str] = None,
    ) -> None:
        await self.chat_store.append_message(username, role, content, thread_id=thread_id)
        effective_thread_id = self._normalize_thread_id(thread_id)
        await self._mirror_best_effort(
            "append_message",
            username=username,
            thread_id=effective_thread_id,
            action=lambda: self.db_store.append_message(username, effective_thread_id, role, content),
        )

    async def clear_thread(
        self,
        username: str,
        *,
        thread_id: Optional[str] = None,
        preserve_thread: bool = True,
    ) -> None:
        await self.chat_store.clear_history(
            username,
            thread_id=thread_id,
            preserve_thread=preserve_thread,
        )
        effective_thread_id = self._normalize_thread_id(thread_id)
        await self._mirror_best_effort(
            "clear_thread",
            username=username,
            thread_id=effective_thread_id,
            action=lambda: self.db_store.delete_thread_messages(username, effective_thread_id),
        )

    async def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        normalized_messages = self._normalize_snapshot(messages)
        await self.chat_store.clear_history(
            username,
            thread_id=thread_id,
            preserve_thread=True,
        )
        for item in normalized_messages:
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            await self.chat_store.append_message(username, role, content, thread_id=thread_id)
        await self._mirror_best_effort(
            "replace_thread_snapshot",
            username=username,
            thread_id=self._normalize_thread_id(thread_id),
            action=lambda: self.db_store.replace_thread_snapshot(username, self._normalize_thread_id(thread_id), normalized_messages),
        )

    def _normalize_thread_id(self, thread_id: Optional[str]) -> str:
        normalized_thread_id = (thread_id or "").strip()
        return normalized_thread_id or DEFAULT_THREAD_ID

    def _normalize_snapshot(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        normalized_messages: list[dict[str, str]] = []
        for item in messages:
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized_messages.append({"role": role, "content": content})
        return normalized_messages

    async def _mirror_best_effort(
        self,
        operation: str,
        *,
        username: str,
        thread_id: str,
        action: Any,
    ) -> None:
        if not self.dual_write_enabled or self.db_store is None:
            return
        try:
            await asyncio.to_thread(action)
        except Exception:
            self.logger.exception(
                "Conversation dual-write %s failed for user=%s thread_id=%s",
                operation,
                username,
                thread_id,
            )


def create_conversation_write_coordinator(
    chat_store: ConversationWriteBackend,
    *,
    db_store: Optional[ConversationWriteMirrorStore] = None,
    dual_write_enabled: bool = False,
    logger: Optional[logging.Logger] = None,
) -> RedisConversationWriteCoordinator:
    return RedisConversationWriteCoordinator(
        chat_store,
        db_store=db_store,
        dual_write_enabled=dual_write_enabled,
        logger=logger,
    )

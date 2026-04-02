from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, Sequence


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


class RedisConversationWriteCoordinator:
    def __init__(self, chat_store: ConversationWriteBackend):
        self.chat_store = chat_store

    async def ensure_thread(self, username: str, *, thread_id: Optional[str] = None) -> str:
        return await self.chat_store.create_thread(username, thread_id=thread_id)

    async def append_message(
        self,
        username: str,
        role: str,
        content: str,
        *,
        thread_id: Optional[str] = None,
    ) -> None:
        await self.chat_store.append_message(username, role, content, thread_id=thread_id)

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

    async def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        await self.clear_thread(username, thread_id=thread_id)
        for item in messages:
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            await self.append_message(username, role, content, thread_id=thread_id)


def create_conversation_write_coordinator(
    chat_store: ConversationWriteBackend,
) -> RedisConversationWriteCoordinator:
    return RedisConversationWriteCoordinator(chat_store)

import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_write_coordinator import create_conversation_write_coordinator


class FakeChatStore:
    def __init__(self):
        self.create_thread_calls: list[tuple[str, str | None]] = []
        self.append_message_calls: list[tuple[str, str, str, str | None]] = []
        self.clear_history_calls: list[tuple[str, str | None, bool]] = []

    async def create_thread(self, username: str, *, thread_id: str | None = None) -> str:
        self.create_thread_calls.append((username, thread_id))
        return thread_id or "default"

    async def append_message(
        self,
        username: str,
        role: str,
        content: str,
        *,
        thread_id: str | None = None,
    ) -> None:
        self.append_message_calls.append((username, role, content, thread_id))

    async def clear_history(
        self,
        username: str,
        *,
        thread_id: str | None = None,
        preserve_thread: bool = True,
    ) -> None:
        self.clear_history_calls.append((username, thread_id, preserve_thread))


class ConversationWriteCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_thread_delegates_to_chat_store(self):
        chat_store = FakeChatStore()
        coordinator = create_conversation_write_coordinator(chat_store)

        thread_id = await coordinator.ensure_thread("alice", thread_id="case-1")

        self.assertEqual(thread_id, "case-1")
        self.assertEqual(chat_store.create_thread_calls, [("alice", "case-1")])

    async def test_append_message_delegates_to_chat_store(self):
        chat_store = FakeChatStore()
        coordinator = create_conversation_write_coordinator(chat_store)

        await coordinator.append_message("alice", "assistant", "Ответ", thread_id="case-1")

        self.assertEqual(
            chat_store.append_message_calls,
            [("alice", "assistant", "Ответ", "case-1")],
        )

    async def test_clear_thread_delegates_with_preserve_semantics(self):
        chat_store = FakeChatStore()
        coordinator = create_conversation_write_coordinator(chat_store)

        await coordinator.clear_thread("alice", thread_id="case-1", preserve_thread=False)

        self.assertEqual(chat_store.clear_history_calls, [("alice", "case-1", False)])

    async def test_replace_thread_snapshot_replays_only_valid_messages(self):
        chat_store = FakeChatStore()
        coordinator = create_conversation_write_coordinator(chat_store)

        await coordinator.replace_thread_snapshot(
            "alice",
            "case-1",
            [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Здравствуйте"},
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "   "},
            ],
        )

        self.assertEqual(chat_store.clear_history_calls, [("alice", "case-1", True)])
        self.assertEqual(
            chat_store.append_message_calls,
            [
                ("alice", "user", "Привет", "case-1"),
                ("alice", "assistant", "Здравствуйте", "case-1"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

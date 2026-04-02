import logging
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


class FakeDbStore:
    def __init__(self, *, fail_operation: str | None = None):
        self.fail_operation = fail_operation
        self.create_or_get_thread_calls: list[tuple[str, str]] = []
        self.append_message_calls: list[tuple[str, str, str, str]] = []
        self.delete_thread_messages_calls: list[tuple[str, str]] = []
        self.replace_thread_snapshot_calls: list[tuple[str, str, list[dict[str, str]]]] = []

    def create_or_get_thread(self, username: str, thread_id: str) -> object:
        self.create_or_get_thread_calls.append((username, thread_id))
        if self.fail_operation == "ensure_thread":
            raise RuntimeError("db ensure failed")
        return object()

    def append_message(self, username: str, thread_id: str, role: str, content: str) -> object:
        self.append_message_calls.append((username, thread_id, role, content))
        if self.fail_operation == "append_message":
            raise RuntimeError("db append failed")
        return object()

    def delete_thread_messages(self, username: str, thread_id: str) -> int:
        self.delete_thread_messages_calls.append((username, thread_id))
        if self.fail_operation == "clear_thread":
            raise RuntimeError("db clear failed")
        return 1

    def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: list[dict[str, str]],
    ) -> object:
        self.replace_thread_snapshot_calls.append((username, thread_id, list(messages)))
        if self.fail_operation == "replace_thread_snapshot":
            raise RuntimeError("db replace failed")
        return object()


class ConversationWriteDualWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_thread_dual_writes_to_db_store(self):
        chat_store = FakeChatStore()
        db_store = FakeDbStore()
        coordinator = create_conversation_write_coordinator(
            chat_store,
            db_store=db_store,
            dual_write_enabled=True,
        )

        thread_id = await coordinator.ensure_thread("alice", thread_id="case-1")

        self.assertEqual(thread_id, "case-1")
        self.assertEqual(chat_store.create_thread_calls, [("alice", "case-1")])
        self.assertEqual(db_store.create_or_get_thread_calls, [("alice", "case-1")])

    async def test_append_and_clear_dual_write_to_db_store(self):
        chat_store = FakeChatStore()
        db_store = FakeDbStore()
        coordinator = create_conversation_write_coordinator(
            chat_store,
            db_store=db_store,
            dual_write_enabled=True,
        )

        await coordinator.append_message("alice", "assistant", "Ответ", thread_id="case-1")
        await coordinator.clear_thread("alice", thread_id="case-1")

        self.assertEqual(
            db_store.append_message_calls,
            [("alice", "case-1", "assistant", "Ответ")],
        )
        self.assertEqual(db_store.delete_thread_messages_calls, [("alice", "case-1")])

    async def test_replace_thread_snapshot_dual_writes_once_via_replace_snapshot(self):
        chat_store = FakeChatStore()
        db_store = FakeDbStore()
        coordinator = create_conversation_write_coordinator(
            chat_store,
            db_store=db_store,
            dual_write_enabled=True,
        )

        await coordinator.replace_thread_snapshot(
            "alice",
            "case-1",
            [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Здравствуйте"},
                {"role": "system", "content": "ignored"},
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
        self.assertEqual(
            db_store.replace_thread_snapshot_calls,
            [
                (
                    "alice",
                    "case-1",
                    [
                        {"role": "user", "content": "Привет"},
                        {"role": "assistant", "content": "Здравствуйте"},
                    ],
                )
            ],
        )
        self.assertEqual(db_store.append_message_calls, [])
        self.assertEqual(db_store.delete_thread_messages_calls, [])

    async def test_db_secondary_write_failures_are_logged_and_swallowed(self):
        chat_store = FakeChatStore()
        db_store = FakeDbStore(fail_operation="append_message")
        logger = logging.getLogger("test.conversation_write_dual_write")
        coordinator = create_conversation_write_coordinator(
            chat_store,
            db_store=db_store,
            dual_write_enabled=True,
            logger=logger,
        )

        with self.assertLogs("test.conversation_write_dual_write", level="ERROR") as captured:
            await coordinator.append_message("alice", "assistant", "Ответ", thread_id="case-1")

        self.assertEqual(
            chat_store.append_message_calls,
            [("alice", "assistant", "Ответ", "case-1")],
        )
        self.assertTrue(any("Conversation dual-write append_message failed" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()

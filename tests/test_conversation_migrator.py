import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_migrator import (
    migrate_all_threads_for_user,
    migrate_thread_for_user,
)
from persistence.conversation_store import ConversationStore
from persistence.database import close_conversation_persistence, init_conversation_persistence


class FakeSourceStore:
    def __init__(self, histories: dict[str, list[dict[str, object]]]):
        self.histories = histories

    async def list_threads(self, username: str) -> list[dict[str, object]]:
        return [{"thread_id": thread_id} for thread_id in self.histories.keys()]

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, object]]:
        return list(self.histories.get(thread_id or "default", []))


class ConversationMigratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_migrate_thread_for_user_reads_source_and_writes_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/migrator-thread.db")
            try:
                store = ConversationStore(runtime.session_factory)
                source = FakeSourceStore(
                    {
                        "default": [
                            {"role": "user", "content": "Привет"},
                            {"role": "assistant", "content": "Здравствуйте"},
                        ]
                    }
                )

                result = await migrate_thread_for_user(source, store, "alice", "default")

                self.assertTrue(result.migrated)
                self.assertFalse(result.skipped_empty)
                self.assertEqual(result.message_count, 2)
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "default")],
                    ["Привет", "Здравствуйте"],
                )
            finally:
                close_conversation_persistence(runtime)

    async def test_migrate_thread_for_user_skips_empty_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/migrator-empty.db")
            try:
                store = ConversationStore(runtime.session_factory)
                source = FakeSourceStore({"default": []})

                result = await migrate_thread_for_user(source, store, "alice", "default")

                self.assertFalse(result.migrated)
                self.assertTrue(result.skipped_empty)
                self.assertEqual(result.message_count, 0)
                self.assertEqual(store.get_messages("alice", "default"), [])
            finally:
                close_conversation_persistence(runtime)

    async def test_migrate_all_threads_for_user_returns_summary_and_ignores_empty_threads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/migrator-all.db")
            try:
                store = ConversationStore(runtime.session_factory)
                source = FakeSourceStore(
                    {
                        "default": [
                            {"role": "user", "content": "A"},
                            {"role": "assistant", "content": "B"},
                        ],
                        "other": [
                            {"role": "user", "content": "C"},
                        ],
                        "empty": [],
                    }
                )

                result = await migrate_all_threads_for_user(source, store, "alice")

                self.assertEqual(result.username, "alice")
                self.assertEqual(result.migrated_thread_count, 2)
                self.assertEqual(result.migrated_message_count, 3)
                self.assertEqual(result.skipped_empty_threads, ("empty",))
                self.assertEqual([item.content for item in store.get_messages("alice", "default")], ["A", "B"])
                self.assertEqual([item.content for item in store.get_messages("alice", "other")], ["C"])
            finally:
                close_conversation_persistence(runtime)

    async def test_migrate_all_threads_for_user_is_idempotent_for_same_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/migrator-idempotent.db")
            try:
                store = ConversationStore(runtime.session_factory)
                source = FakeSourceStore(
                    {
                        "default": [
                            {"role": "user", "content": "A"},
                            {"role": "assistant", "content": "B"},
                        ]
                    }
                )

                first = await migrate_all_threads_for_user(source, store, "alice")
                second = await migrate_all_threads_for_user(source, store, "alice")

                self.assertEqual(first.migrated_thread_count, 1)
                self.assertEqual(second.migrated_thread_count, 1)
                self.assertEqual([item.content for item in store.get_messages("alice", "default")], ["A", "B"])
                self.assertEqual(len(store.get_messages("alice", "default")), 2)
            finally:
                close_conversation_persistence(runtime)


if __name__ == "__main__":
    unittest.main()

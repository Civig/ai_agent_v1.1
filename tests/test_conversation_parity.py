import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_parity import (
    PARITY_CONTENT_MISMATCH,
    PARITY_EMPTY_THREAD,
    PARITY_MATCHED,
    PARITY_MISSING_IN_DB,
    PARITY_MISSING_IN_SOURCE,
    compare_all_threads_for_user,
    compare_thread_for_user,
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


class ConversationParityTests(unittest.IsolatedAsyncioTestCase):
    async def test_compare_thread_for_user_reports_matched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/parity-match.db")
            try:
                store = ConversationStore(runtime.session_factory)
                store.import_thread_snapshot(
                    "alice",
                    "default",
                    [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}],
                )
                source = FakeSourceStore(
                    {"default": [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]}
                )

                result = await compare_thread_for_user(source, store, "alice", "default")

                self.assertEqual(result.status, PARITY_MATCHED)
                self.assertEqual(result.source_message_count, 2)
                self.assertEqual(result.db_message_count, 2)
            finally:
                close_conversation_persistence(runtime)

    async def test_compare_thread_for_user_reports_missing_and_mismatch_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/parity-cases.db")
            try:
                store = ConversationStore(runtime.session_factory)
                store.import_thread_snapshot("alice", "db-only", [{"role": "user", "content": "db"}])
                store.import_thread_snapshot("alice", "mismatch", [{"role": "user", "content": "db"}])

                source = FakeSourceStore(
                    {
                        "source-only": [{"role": "user", "content": "src"}],
                        "mismatch": [{"role": "user", "content": "src"}],
                    }
                )

                missing_in_db = await compare_thread_for_user(source, store, "alice", "source-only")
                missing_in_source = await compare_thread_for_user(source, store, "alice", "db-only")
                mismatch = await compare_thread_for_user(source, store, "alice", "mismatch")

                self.assertEqual(missing_in_db.status, PARITY_MISSING_IN_DB)
                self.assertEqual(missing_in_source.status, PARITY_MISSING_IN_SOURCE)
                self.assertEqual(mismatch.status, PARITY_CONTENT_MISMATCH)
            finally:
                close_conversation_persistence(runtime)

    async def test_compare_thread_for_user_reports_empty_thread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/parity-empty.db")
            try:
                store = ConversationStore(runtime.session_factory)
                source = FakeSourceStore({"default": []})

                result = await compare_thread_for_user(source, store, "alice", "default")

                self.assertEqual(result.status, PARITY_EMPTY_THREAD)
                self.assertEqual(result.source_message_count, 0)
                self.assertEqual(result.db_message_count, 0)
            finally:
                close_conversation_persistence(runtime)

    async def test_compare_all_threads_for_user_returns_deterministic_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/parity-all.db")
            try:
                store = ConversationStore(runtime.session_factory)
                store.import_thread_snapshot("alice", "matched", [{"role": "user", "content": "A"}])
                store.import_thread_snapshot("alice", "db-only", [{"role": "user", "content": "DB"}])
                store.import_thread_snapshot("alice", "mismatch", [{"role": "user", "content": "DB"}])

                source = FakeSourceStore(
                    {
                        "matched": [{"role": "user", "content": "A"}],
                        "source-only": [{"role": "user", "content": "SRC"}],
                        "mismatch": [{"role": "user", "content": "SRC"}],
                        "empty": [],
                    }
                )

                result = await compare_all_threads_for_user(source, store, "alice")

                self.assertEqual(result.username, "alice")
                self.assertEqual(result.matched_threads, ("matched",))
                self.assertEqual(result.missing_in_db_threads, ("source-only",))
                self.assertEqual(result.missing_in_source_threads, ("db-only",))
                self.assertEqual(result.content_mismatch_threads, ("mismatch",))
                self.assertEqual(result.empty_threads, ("empty",))
            finally:
                close_conversation_persistence(runtime)


if __name__ == "__main__":
    unittest.main()

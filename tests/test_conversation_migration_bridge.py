import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_migration import (
    migrate_thread_from_history,
    migrate_threads_for_user,
    normalize_history_to_snapshot,
)
from persistence.conversation_store import ConversationStore
from persistence.database import close_conversation_persistence, init_conversation_persistence


class ConversationMigrationBridgeTests(unittest.TestCase):
    def test_normalize_history_to_snapshot_accepts_redis_shaped_messages(self):
        snapshot = normalize_history_to_snapshot(
            [
                {"role": "user", "content": "Привет", "created_at": 123},
                {"role": "assistant", "content": "Здравствуйте", "created_at": 124},
            ]
        )

        self.assertEqual([item.role for item in snapshot], ["user", "assistant"])
        self.assertEqual([item.content for item in snapshot], ["Привет", "Здравствуйте"])

    def test_migrate_thread_from_history_is_idempotent_for_same_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/thread-migrate.db")
            try:
                store = ConversationStore(runtime.session_factory)
                history = [
                    {"role": "user", "content": "A", "created_at": 1},
                    {"role": "assistant", "content": "B", "created_at": 2},
                ]

                first = migrate_thread_from_history(store, "alice", "default", history)
                second = migrate_thread_from_history(store, "alice", "default", history)

                self.assertEqual([item.id for item in first], [item.id for item in second])
                self.assertEqual([item.content for item in store.get_messages("alice", "default")], ["A", "B"])
            finally:
                close_conversation_persistence(runtime)

    def test_migrate_threads_for_user_moves_multiple_thread_snapshots_without_cross_thread_corruption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/multi-migrate.db")
            try:
                store = ConversationStore(runtime.session_factory)

                result = migrate_threads_for_user(
                    store,
                    "alice",
                    {
                        "default": [
                            {"role": "user", "content": "первый"},
                            {"role": "assistant", "content": "ответ"},
                        ],
                        "other": [
                            {"role": "user", "content": "соседний"},
                        ],
                    },
                )

                self.assertEqual(sorted(result.keys()), ["default", "other"])
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "default")],
                    ["первый", "ответ"],
                )
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "other")],
                    ["соседний"],
                )
            finally:
                close_conversation_persistence(runtime)

    def test_bridge_rejects_invalid_history_payload(self):
        with self.assertRaisesRegex(ValueError, "role"):
            normalize_history_to_snapshot([{"content": "payload"}])

        with self.assertRaisesRegex(ValueError, "content"):
            normalize_history_to_snapshot([{"role": "user", "content": ""}])


if __name__ == "__main__":
    unittest.main()

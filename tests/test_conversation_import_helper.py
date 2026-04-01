import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_store import ConversationSnapshotMessage, ConversationStore
from persistence.database import close_conversation_persistence, init_conversation_persistence


class ConversationImportHelperTests(unittest.TestCase):
    def test_import_thread_snapshot_creates_thread_and_preserves_message_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/import.db")
            try:
                store = ConversationStore(runtime.session_factory)

                imported = store.import_thread_snapshot(
                    "alice",
                    "default",
                    [
                        {"role": "user", "content": "Привет"},
                        {"role": "assistant", "content": "Здравствуйте"},
                    ],
                )

                self.assertEqual([item.message_index for item in imported], [0, 1])
                self.assertEqual([item.role for item in imported], ["user", "assistant"])
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "default")],
                    ["Привет", "Здравствуйте"],
                )
            finally:
                close_conversation_persistence(runtime)

    def test_import_thread_snapshot_is_idempotent_for_same_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/idempotent.db")
            try:
                store = ConversationStore(runtime.session_factory)
                snapshot = [
                    ConversationSnapshotMessage(role="user", content="A"),
                    ConversationSnapshotMessage(role="assistant", content="B"),
                ]

                first = store.import_thread_snapshot("alice", "default", snapshot)
                second = store.import_thread_snapshot("alice", "default", snapshot)

                self.assertEqual([item.id for item in first], [item.id for item in second])
                self.assertEqual(len(store.get_messages("alice", "default")), 2)
            finally:
                close_conversation_persistence(runtime)

    def test_import_thread_snapshot_replaces_changed_snapshot_without_touching_other_thread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/replace.db")
            try:
                store = ConversationStore(runtime.session_factory)
                store.import_thread_snapshot(
                    "alice",
                    "default",
                    [{"role": "user", "content": "старое"}],
                )
                store.import_thread_snapshot(
                    "alice",
                    "neighbor",
                    [{"role": "user", "content": "соседний"}],
                )

                replaced = store.import_thread_snapshot(
                    "alice",
                    "default",
                    [
                        {"role": "user", "content": "новое"},
                        {"role": "assistant", "content": "ответ"},
                    ],
                )

                self.assertEqual([item.content for item in replaced], ["новое", "ответ"])
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "default")],
                    ["новое", "ответ"],
                )
                self.assertEqual(
                    [item.content for item in store.get_messages("alice", "neighbor")],
                    ["соседний"],
                )
            finally:
                close_conversation_persistence(runtime)

    def test_replace_thread_snapshot_force_replaces_existing_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/force-replace.db")
            try:
                store = ConversationStore(runtime.session_factory)
                first = store.import_thread_snapshot(
                    "alice",
                    "default",
                    [{"role": "user", "content": "A"}],
                )
                replaced = store.replace_thread_snapshot(
                    "alice",
                    "default",
                    [{"role": "assistant", "content": "B"}],
                )

                self.assertEqual([item.content for item in replaced], ["B"])
                self.assertEqual([item.role for item in replaced], ["assistant"])
                self.assertEqual([item.content for item in store.get_messages("alice", "default")], ["B"])
                self.assertEqual([item.content for item in first], ["A"])
            finally:
                close_conversation_persistence(runtime)


if __name__ == "__main__":
    unittest.main()

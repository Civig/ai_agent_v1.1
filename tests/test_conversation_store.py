import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.database import close_conversation_persistence, init_conversation_persistence
from persistence.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_create_get_and_list_threads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/store.db")
            try:
                store = ConversationStore(runtime.session_factory)

                default_thread = store.create_or_get_thread("alice", "default")
                repeated_thread = store.create_or_get_thread("alice", "default")
                secondary_thread = store.create_or_get_thread("alice", "investigation")
                threads = store.list_threads("alice")

                self.assertEqual(default_thread.id, repeated_thread.id)
                self.assertEqual(store.get_thread("alice", "default").thread_id, "default")
                self.assertEqual(store.get_thread("alice", "missing"), None)
                self.assertEqual([thread.thread_id for thread in threads], ["investigation", "default"])
                self.assertEqual(secondary_thread.thread_id, "investigation")
            finally:
                close_conversation_persistence(runtime)

    def test_append_and_read_messages_in_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/messages.db")
            try:
                store = ConversationStore(runtime.session_factory)

                first = store.append_message("alice", "default", "user", "Привет")
                second = store.append_message("alice", "default", "assistant", "Здравствуйте")
                messages = store.get_messages("alice", "default")
                thread = store.get_thread("alice", "default")

                self.assertEqual(first.message_index, 0)
                self.assertEqual(second.message_index, 1)
                self.assertEqual([message.role for message in messages], ["user", "assistant"])
                self.assertEqual([message.content for message in messages], ["Привет", "Здравствуйте"])
                self.assertIsNotNone(thread)
            finally:
                close_conversation_persistence(runtime)

    def test_delete_thread_messages_affects_only_target_thread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/clear.db")
            try:
                store = ConversationStore(runtime.session_factory)

                store.append_message("alice", "default", "user", "Первый")
                store.append_message("alice", "default", "assistant", "Ответ")
                store.append_message("alice", "other", "user", "Соседний")

                deleted = store.delete_thread_messages("alice", "default")

                self.assertEqual(deleted, 2)
                self.assertEqual(store.get_messages("alice", "default"), [])
                self.assertEqual(len(store.get_messages("alice", "other")), 1)
                self.assertIsNotNone(store.get_thread("alice", "default"))
            finally:
                close_conversation_persistence(runtime)

    def test_store_validates_required_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = init_conversation_persistence(f"sqlite+pysqlite:///{tmpdir}/validation.db")
            try:
                store = ConversationStore(runtime.session_factory)

                with self.assertRaisesRegex(ValueError, "username"):
                    store.create_or_get_thread("", "default")
                with self.assertRaisesRegex(ValueError, "thread_id"):
                    store.create_or_get_thread("alice", "")
                with self.assertRaisesRegex(ValueError, "role"):
                    store.append_message("alice", "default", "", "payload")
                with self.assertRaisesRegex(ValueError, "content"):
                    store.append_message("alice", "default", "user", "")
            finally:
                close_conversation_persistence(runtime)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import config as config_module
from persistence.conversation_models import ConversationMessage, ConversationThread
from persistence.database import (
    close_conversation_persistence,
    init_conversation_persistence,
    init_conversation_persistence_from_settings,
)


class ConversationPersistenceGroundworkTests(unittest.TestCase):
    def test_settings_default_to_safe_disabled_persistent_db(self):
        settings = config_module.Settings(SECRET_KEY="x" * 40, COOKIE_SECURE=False)

        self.assertFalse(settings.PERSISTENT_DB_ENABLED)
        self.assertEqual(settings.PERSISTENT_DB_URL, "")
        self.assertFalse(settings.persistent_db_url_configured)
        self.assertFalse(settings.PERSISTENT_DB_ECHO)
        self.assertTrue(settings.PERSISTENT_DB_POOL_PRE_PING)

    def test_init_from_settings_returns_none_when_persistent_db_is_disabled(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            PERSISTENT_DB_ENABLED=False,
            PERSISTENT_DB_URL="sqlite+pysqlite:///:memory:",
        )

        runtime = init_conversation_persistence_from_settings(settings)

        self.assertIsNone(runtime)

    def test_init_from_settings_requires_non_empty_database_url_when_enabled(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            PERSISTENT_DB_ENABLED=True,
            PERSISTENT_DB_URL="",
        )

        with self.assertRaisesRegex(ValueError, "PERSISTENT_DB_URL"):
            init_conversation_persistence_from_settings(settings)

    def test_init_conversation_persistence_creates_thread_and_message_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_url = f"sqlite+pysqlite:///{tmpdir}/conversation-groundwork.db"
            runtime = init_conversation_persistence(database_url)
            try:
                with runtime.session_factory() as session:
                    thread = ConversationThread(username="alice", thread_id="default")
                    session.add(thread)
                    session.flush()
                    session.add(
                        ConversationMessage(
                            thread_pk=thread.id,
                            message_index=0,
                            role="user",
                            content="Привет",
                        )
                    )
                    session.commit()

                with runtime.session_factory() as session:
                    stored_thread = session.query(ConversationThread).filter_by(username="alice", thread_id="default").one()
                    stored_messages = (
                        session.query(ConversationMessage)
                        .filter_by(thread_pk=stored_thread.id)
                        .order_by(ConversationMessage.message_index.asc())
                        .all()
                    )
                    self.assertEqual(stored_thread.username, "alice")
                    self.assertEqual(stored_thread.thread_id, "default")
                    self.assertEqual(len(stored_messages), 1)
                    self.assertEqual(stored_messages[0].role, "user")
                    self.assertEqual(stored_messages[0].content, "Привет")
            finally:
                close_conversation_persistence(runtime)


if __name__ == "__main__":
    unittest.main()

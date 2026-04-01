import os
import tempfile
import unittest

from sqlalchemy import inspect

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import config as config_module
from persistence.database import (
    bootstrap_conversation_persistence_from_settings,
    close_conversation_persistence,
    init_conversation_persistence_from_settings,
)


class ConversationPersistenceBoundaryTests(unittest.TestCase):
    def test_bootstrap_returns_none_when_disabled_even_if_flag_is_true(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            PERSISTENT_DB_ENABLED=False,
            PERSISTENT_DB_BOOTSTRAP_SCHEMA=True,
            PERSISTENT_DB_URL="sqlite+pysqlite:///:memory:",
        )

        runtime = bootstrap_conversation_persistence_from_settings(settings)

        self.assertIsNone(runtime)

    def test_init_from_settings_remains_safe_by_default_without_schema_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL=f"sqlite+pysqlite:///{tmpdir}/default-init.db",
                PERSISTENT_DB_BOOTSTRAP_SCHEMA=True,
            )

            runtime = init_conversation_persistence_from_settings(settings)
            try:
                self.assertIsNotNone(runtime)
                inspector = inspect(runtime.engine)
                self.assertEqual(inspector.get_table_names(), [])
            finally:
                close_conversation_persistence(runtime)

import os
import tempfile
import unittest

from sqlalchemy import inspect

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import config as config_module
from persistence.database import (
    bootstrap_conversation_persistence_from_settings,
    close_conversation_persistence,
    open_conversation_persistence_from_settings,
    resolve_conversation_persistence_settings,
    validate_conversation_persistence_settings,
)


class ConversationPersistenceBootstrapTests(unittest.TestCase):
    def test_resolve_returns_disabled_snapshot_without_requiring_url(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            PERSISTENT_DB_ENABLED=False,
            PERSISTENT_DB_URL="",
        )

        resolved = resolve_conversation_persistence_settings(settings)

        self.assertFalse(resolved.enabled)
        self.assertEqual(resolved.database_url, "")
        self.assertFalse(resolved.bootstrap_schema)

    def test_validate_requires_url_only_when_enabled(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            PERSISTENT_DB_ENABLED=True,
            PERSISTENT_DB_URL="",
        )

        with self.assertRaisesRegex(ValueError, "PERSISTENT_DB_URL"):
            validate_conversation_persistence_settings(settings)

    def test_open_from_settings_does_not_create_schema_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL=f"sqlite+pysqlite:///{tmpdir}/no-schema.db",
                PERSISTENT_DB_BOOTSTRAP_SCHEMA=False,
            )

            runtime = open_conversation_persistence_from_settings(settings)
            try:
                self.assertIsNotNone(runtime)
                inspector = inspect(runtime.engine)
                self.assertEqual(inspector.get_table_names(), [])
            finally:
                close_conversation_persistence(runtime)

    def test_bootstrap_from_settings_creates_schema_only_in_explicit_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL=f"sqlite+pysqlite:///{tmpdir}/bootstrap.db",
                PERSISTENT_DB_BOOTSTRAP_SCHEMA=True,
            )

            runtime = bootstrap_conversation_persistence_from_settings(settings)
            try:
                self.assertIsNotNone(runtime)
                inspector = inspect(runtime.engine)
                self.assertEqual(
                    set(inspector.get_table_names()),
                    {"conversation_messages", "conversation_threads"},
                )
            finally:
                close_conversation_persistence(runtime)

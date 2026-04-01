import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import inspect

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import app as app_module


class FakeAsyncChatStore:
    def __init__(self, *_args, **_kwargs):
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True


class FakeAsyncRateLimiter:
    def __init__(self, *_args, **_kwargs):
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True


class FakeLLMGateway:
    def __init__(self, *_args, **_kwargs):
        self.connected = False
        self.closed = False
        self.catalog = None

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def set_model_catalog(self, catalog) -> None:
        self.catalog = catalog


class AppPersistenceStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_keeps_persistence_disabled_by_default(self):
        test_app = FastAPI(lifespan=app_module.lifespan)

        with (
            patch.object(app_module, "AsyncChatStore", FakeAsyncChatStore),
            patch.object(app_module, "AsyncRateLimiter", FakeAsyncRateLimiter),
            patch.object(app_module, "LLMGateway", FakeLLMGateway),
            patch.object(app_module.settings, "PERSISTENT_DB_ENABLED", False),
            patch.object(app_module.settings, "PERSISTENT_DB_URL", ""),
            patch.object(app_module.settings, "PERSISTENT_DB_BOOTSTRAP_SCHEMA", False),
            patch.object(app_module.settings, "get_available_models", return_value={"demo": {"name": "demo"}}),
        ):
            async with app_module.lifespan(test_app):
                self.assertIsNone(test_app.state.conversation_persistence)
                self.assertIsNone(test_app.state.conversation_db_store)
                self.assertTrue(test_app.state.chat_store.connected)
                self.assertTrue(test_app.state.llm_gateway.connected)

    async def test_lifespan_opens_db_store_without_bootstrap_when_enabled(self):
        test_app = FastAPI(lifespan=app_module.lifespan)

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(app_module, "AsyncChatStore", FakeAsyncChatStore),
                patch.object(app_module, "AsyncRateLimiter", FakeAsyncRateLimiter),
                patch.object(app_module, "LLMGateway", FakeLLMGateway),
                patch.object(app_module.settings, "PERSISTENT_DB_ENABLED", True),
                patch.object(
                    app_module.settings,
                    "PERSISTENT_DB_URL",
                    f"sqlite+pysqlite:///{tmpdir}/startup-open.db",
                ),
                patch.object(app_module.settings, "PERSISTENT_DB_BOOTSTRAP_SCHEMA", False),
                patch.object(app_module.settings, "get_available_models", return_value={"demo": {"name": "demo"}}),
            ):
                async with app_module.lifespan(test_app):
                    self.assertIsNotNone(test_app.state.conversation_persistence)
                    self.assertIsNotNone(test_app.state.conversation_db_store)
                    inspector = inspect(test_app.state.conversation_persistence.runtime.engine)
                    self.assertEqual(inspector.get_table_names(), [])

    async def test_lifespan_bootstraps_schema_only_with_explicit_flag(self):
        test_app = FastAPI(lifespan=app_module.lifespan)

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(app_module, "AsyncChatStore", FakeAsyncChatStore),
                patch.object(app_module, "AsyncRateLimiter", FakeAsyncRateLimiter),
                patch.object(app_module, "LLMGateway", FakeLLMGateway),
                patch.object(app_module.settings, "PERSISTENT_DB_ENABLED", True),
                patch.object(
                    app_module.settings,
                    "PERSISTENT_DB_URL",
                    f"sqlite+pysqlite:///{tmpdir}/startup-bootstrap.db",
                ),
                patch.object(app_module.settings, "PERSISTENT_DB_BOOTSTRAP_SCHEMA", True),
                patch.object(app_module.settings, "get_available_models", return_value={"demo": {"name": "demo"}}),
            ):
                async with app_module.lifespan(test_app):
                    inspector = inspect(test_app.state.conversation_persistence.runtime.engine)
                    self.assertEqual(
                        set(inspector.get_table_names()),
                        {"conversation_messages", "conversation_threads"},
                    )

    async def test_lifespan_fails_fast_on_invalid_enabled_db_settings(self):
        test_app = FastAPI(lifespan=app_module.lifespan)

        with (
            patch.object(app_module, "AsyncChatStore", FakeAsyncChatStore),
            patch.object(app_module, "AsyncRateLimiter", FakeAsyncRateLimiter),
            patch.object(app_module, "LLMGateway", FakeLLMGateway),
            patch.object(app_module.settings, "PERSISTENT_DB_ENABLED", True),
            patch.object(app_module.settings, "PERSISTENT_DB_URL", ""),
            patch.object(app_module.settings, "PERSISTENT_DB_BOOTSTRAP_SCHEMA", False),
            patch.object(app_module.settings, "get_available_models", return_value={"demo": {"name": "demo"}}),
        ):
            with self.assertRaisesRegex(ValueError, "PERSISTENT_DB_URL"):
                async with app_module.lifespan(test_app):
                    self.fail("lifespan should not yield when persistent DB settings are invalid")


if __name__ == "__main__":
    unittest.main()

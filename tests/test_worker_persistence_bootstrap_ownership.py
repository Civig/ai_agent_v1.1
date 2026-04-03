import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

sys.modules.setdefault(
    "httpx",
    SimpleNamespace(
        Response=object,
        AsyncClient=object,
        Timeout=object,
        Limits=object,
        ConnectError=Exception,
        ReadTimeout=Exception,
        RemoteProtocolError=Exception,
        HTTPStatusError=Exception,
    ),
)

import worker as worker_module


class FakeGateway:
    def __init__(self, *_args, **_kwargs):
        pass


class FakeChatStore:
    def __init__(self, *_args, **_kwargs):
        pass


class FakeOllamaClient:
    def __init__(self, *_args, **_kwargs):
        pass


class FakeMonitor:
    def __init__(self, *_args, **_kwargs):
        pass


class WorkerPersistenceBootstrapOwnershipTests(unittest.TestCase):
    def test_worker_opens_persistence_runtime_without_schema_bootstrap(self):
        captured: dict[str, object] = {}
        fake_store = object()
        fake_runtime = SimpleNamespace(store=fake_store)

        def fake_open(app_settings, *, bootstrap_schema=None):
            captured["app_settings"] = app_settings
            captured["bootstrap_schema"] = bootstrap_schema
            return fake_runtime

        def fake_coordinator(chat_store, *, db_store=None, dual_write_enabled=False, logger=None):
            captured["db_store"] = db_store
            captured["dual_write_enabled"] = dual_write_enabled
            return "coordinator"

        with (
            patch.object(worker_module, "LLMGateway", FakeGateway),
            patch.object(worker_module, "AsyncChatStore", FakeChatStore),
            patch.object(worker_module, "OllamaWorkerClient", FakeOllamaClient),
            patch.object(worker_module, "LocalResourceMonitor", FakeMonitor),
            patch.object(worker_module, "open_conversation_persistence_runtime", side_effect=fake_open),
            patch.object(worker_module, "create_conversation_write_coordinator", side_effect=fake_coordinator),
            patch.object(worker_module.settings, "PERSISTENT_DB_DUAL_WRITE_CONVERSATION", True),
            patch.object(worker_module.settings, "WORKER_POOL", "chat"),
        ):
            worker = worker_module.LLMWorker()

        self.assertIs(worker.conversation_persistence, fake_runtime)
        self.assertIs(worker.conversation_db_store, fake_store)
        self.assertEqual(captured["bootstrap_schema"], False)
        self.assertIs(captured["db_store"], fake_store)
        self.assertEqual(captured["dual_write_enabled"], True)

    def test_worker_skips_persistence_runtime_when_dual_write_disabled(self):
        with (
            patch.object(worker_module, "LLMGateway", FakeGateway),
            patch.object(worker_module, "AsyncChatStore", FakeChatStore),
            patch.object(worker_module, "OllamaWorkerClient", FakeOllamaClient),
            patch.object(worker_module, "LocalResourceMonitor", FakeMonitor),
            patch.object(worker_module, "open_conversation_persistence_runtime") as open_runtime,
            patch.object(worker_module, "create_conversation_write_coordinator", return_value="coordinator"),
            patch.object(worker_module.settings, "PERSISTENT_DB_DUAL_WRITE_CONVERSATION", False),
            patch.object(worker_module.settings, "WORKER_POOL", "chat"),
        ):
            worker = worker_module.LLMWorker()

        open_runtime.assert_not_called()
        self.assertIsNone(worker.conversation_persistence)
        self.assertIsNone(worker.conversation_db_store)


if __name__ == "__main__":
    unittest.main()

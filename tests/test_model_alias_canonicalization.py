import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
import auth_kerberos as auth_module
from config import Settings, resolve_model_catalog_key
from llm_gateway import LLMGateway
from tests.test_scheduler_chat_admission_stall import FakeRedis


LIVE_CATALOG = {
    "mistral:latest": {
        "name": "mistral:latest",
        "description": "Mistral",
        "size": str(4 * 1024 * 1024 * 1024),
        "status": "active",
    },
    "qwen2.5:14b": {
        "name": "qwen2.5:14b",
        "description": "Qwen",
        "size": str(14 * 1024 * 1024 * 1024),
        "status": "active",
    },
}

REGISTRY_CATALOG = {
    "mistral": {
        "model_key": "mistral",
        "display_name": "Mistral",
        "category": "general",
        "enabled_for_validation_user": True,
        "sort_order": 1,
    },
    "qwen2.5:14b": {
        "model_key": "qwen2.5:14b",
        "display_name": "Qwen",
        "category": "general",
        "enabled_for_validation_user": True,
        "sort_order": 2,
    },
}

POLICY_CATALOG = {
    "general": {
        "category": "general",
        "display_name": "General",
        "models": {
            "mistral": {"model_key": "mistral", "display_name": "Mistral", "category": "general"},
            "qwen2.5:14b": {"model_key": "qwen2.5:14b", "display_name": "Qwen", "category": "general"},
        },
    }
}


class ModelAliasCanonicalizationTests(unittest.TestCase):
    def test_short_default_model_matches_latest_live_tag(self):
        settings = Settings(SECRET_KEY="x" * 40, COOKIE_SECURE=False, DEFAULT_MODEL="mistral")

        self.assertEqual(resolve_model_catalog_key("mistral", LIVE_CATALOG), "mistral:latest")
        self.assertEqual(settings.pick_available_model(LIVE_CATALOG), "mistral:latest")

    def test_explicit_tag_model_keeps_exact_match(self):
        settings = Settings(SECRET_KEY="x" * 40, COOKIE_SECURE=False, DEFAULT_MODEL="qwen2.5:14b")

        self.assertEqual(resolve_model_catalog_key("qwen2.5:14b", LIVE_CATALOG), "qwen2.5:14b")
        self.assertEqual(settings.pick_available_model(LIVE_CATALOG), "qwen2.5:14b")

    def test_api_resolver_returns_canonical_live_key_for_short_alias(self):
        resolved = app_module.resolve_model_identifier("mistral", LIVE_CATALOG)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["key"], "mistral:latest")
        self.assertEqual(resolved["name"], "mistral:latest")

    def test_validation_user_default_model_access_accepts_short_alias(self):
        with patch.object(auth_module.settings, "DEFAULT_MODEL", "mistral"):
            access = auth_module.get_validation_user_default_model_access(
                {"username": "aitest"},
                LIVE_CATALOG,
                REGISTRY_CATALOG,
            )

        self.assertIn("mistral:latest", access)
        self.assertEqual(access["mistral:latest"]["name"], "mistral:latest")
        self.assertEqual(access["mistral:latest"]["policy_display_name"], "Mistral")

    def test_policy_access_uses_canonical_live_key_for_short_catalog_entry(self):
        user_info = {"username": "alice", "groups": []}
        with patch.object(auth_module, "load_model_registry_catalog", return_value=REGISTRY_CATALOG), patch.object(
            auth_module, "load_model_policy_catalog", return_value=POLICY_CATALOG
        ), patch.object(auth_module.settings, "INSTALL_TEST_USER", ""):
            access = auth_module.get_allowed_models_for_user(user_info, LIVE_CATALOG)

        self.assertIn("mistral:latest", access)
        self.assertIn("qwen2.5:14b", access)
        self.assertNotIn("mistral", access)


class GatewayModelAliasCanonicalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_job_stores_canonical_live_model_key_for_short_alias(self):
        gateway = LLMGateway("redis://test")
        gateway.redis = FakeRedis()
        gateway.available = True
        gateway.get_total_pending_jobs = AsyncMock(return_value=0)
        gateway._dynamic_queue_limit = AsyncMock(return_value=100)
        gateway.get_model_catalog = AsyncMock(return_value=LIVE_CATALOG)

        job_id = await gateway.enqueue_job(
            username="alice",
            model_key="mistral",
            model_name="mistral",
            prompt="hello",
            history=[],
        )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["model_key"], "mistral:latest")
        self.assertEqual(job["model_name"], "mistral:latest")


if __name__ == "__main__":
    unittest.main()

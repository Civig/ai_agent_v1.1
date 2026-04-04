import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class FakeChatStore:
    def __init__(self):
        self.get_history = AsyncMock(return_value=[])


class AdminDashboardRouteRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_page_still_renders_chat_template(self):
        chat_store = FakeChatStore()
        request = type(
            "Req",
            (),
            {
                "query_params": {},
                "url": type("Url", (), {"hostname": "srv-ai"})(),
                "app": type(
                    "App",
                    (),
                    {
                        "state": type(
                            "State",
                            (),
                            {
                                "chat_store": chat_store,
                                "llm_gateway": type("Gateway", (), {"get_model_catalog": AsyncMock(return_value={"demo": {"name": "demo"}})})(),
                            },
                        )()
                    },
                )(),
            },
        )()
        captured = {}

        def fake_template_response(req, name, context):
            captured["name"] = name
            captured["context"] = context
            return context

        with (
            patch.object(app_module, "build_conversation_writer", return_value=object()),
            patch.object(app_module, "load_thread_summaries", AsyncMock(return_value=[{"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 0}])),
            patch.object(app_module, "resolve_runtime_model", AsyncMock(return_value={"key": "demo", "name": "demo", "description": "demo"})),
            patch.object(app_module.templates, "TemplateResponse", side_effect=fake_template_response),
        ):
            result = await app_module.chat_page(
                request,
                thread_id=None,
                current_user={
                    "username": "alice",
                    "display_name": "Alice",
                    "email": "alice@corp.local",
                },
            )

        self.assertEqual(captured["name"], "chat.html")
        self.assertEqual(result["thread_id"], "default")
        self.assertEqual(result["threads"][0]["id"], "default")


if __name__ == "__main__":
    unittest.main()

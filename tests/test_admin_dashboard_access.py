import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


def build_request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace(llm_gateway=object()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/dashboard",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


class AdminDashboardAccessTests(unittest.IsolatedAsyncioTestCase):
    def test_guard_allows_aitest_only(self):
        user = {"username": "aitest", "display_name": "AI Test", "email": "aitest@corp.local"}

        result = app_module.get_admin_dashboard_user_required(current_user=user)

        self.assertIs(result, user)

    def test_guard_rejects_non_aitest_user(self):
        with self.assertRaises(HTTPException) as error:
            app_module.get_admin_dashboard_user_required(
                current_user={"username": "alice", "display_name": "Alice", "email": "alice@corp.local"}
            )

        self.assertEqual(error.exception.status_code, 403)

    async def test_dashboard_route_renders_template_for_allowed_user(self):
        request = build_request()
        captured = {}

        def fake_template_response(req, name, context):
            captured["request"] = req
            captured["name"] = name
            captured["context"] = context
            return context

        with patch.object(app_module.templates, "TemplateResponse", side_effect=fake_template_response):
            result = await app_module.admin_dashboard_page(
                request,
                current_user={"username": "aitest"},
            )

        self.assertEqual(captured["name"], "admin_dashboard.html")
        self.assertEqual(result["current_user"]["username"], "aitest")
        self.assertEqual(result["current_user"]["display_name"], "aitest")
        self.assertTrue(result["is_authenticated"])


if __name__ == "__main__":
    unittest.main()

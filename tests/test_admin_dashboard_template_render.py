import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class AdminDashboardTemplateRenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_dashboard_route_renders_expected_template_and_bootstrap(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), url=SimpleNamespace(hostname="srv-ai"))
        captured = {}

        def fake_template_response(req, name, context):
            captured["request"] = req
            captured["name"] = name
            captured["context"] = context
            return context

        with patch.object(app_module.templates, "TemplateResponse", side_effect=fake_template_response):
            result = await app_module.admin_dashboard_page(
                request,
                current_user={
                    "username": "aitest",
                    "display_name": "AI Test",
                    "email": "aitest@corp.local",
                },
            )

        self.assertEqual(captured["name"], "admin_dashboard.html")
        self.assertTrue(result["is_authenticated"])
        self.assertEqual(result["dashboard_api_url"], "/api/admin/dashboard/summary")
        self.assertEqual(result["dashboard_refresh_interval_ms"], app_module.ADMIN_DASHBOARD_REFRESH_INTERVAL_MS)


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from fastapi import FastAPI
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class AdminDashboardTemplateRenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_dashboard_route_renders_expected_template_and_bootstrap(self):
        app = FastAPI()
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/admin/dashboard",
                "headers": [],
                "query_string": b"",
                "scheme": "https",
                "server": ("127.0.0.1", 443),
                "client": ("127.0.0.1", 12345),
                "app": app,
            }
        )

        response = await app_module.admin_dashboard_page(
            request,
            current_user={
                "username": "aitest",
                "display_name": "AI Test",
                "email": "aitest@corp.local",
            },
        )

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin Dashboard", html)
        self.assertIn("Управление нагрузкой", html)
        self.assertIn("Что происходит с мощностью и очередями прямо сейчас", html)
        self.assertIn("Оценка запаса", html)
        self.assertIn("Что ограничивает систему сейчас", html)
        self.assertIn("Что это значит для масштабирования", html)
        self.assertIn("Предупреждения и рекомендации", html)
        self.assertIn("Как читать панель", html)
        self.assertIn("Всего задач в очередях", html)
        self.assertIn("Давление очереди", html)
        self.assertIn("Активные воркеры", html)
        self.assertIn("Доступные вычислительные цели", html)
        self.assertIn("/api/admin/dashboard/summary", html)


if __name__ == "__main__":
    unittest.main()

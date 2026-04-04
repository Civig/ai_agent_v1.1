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
        self.assertIn("Быстрый ответ: всё ли штатно, есть ли запас и будет ли ждать следующий chat-запрос.", html)
        self.assertIn("Что ограничивает систему", html)
        self.assertIn("Следующий chat-запрос", html)
        self.assertIn("Масштабирование", html)
        self.assertIn("Предупреждения", html)
        self.assertIn("Как читать панель", html)
        self.assertIn("Термины, сигналы и ограничения", html)
        self.assertIn('id="kpiGrid"', html)
        self.assertIn("Давление очереди", html)
        self.assertIn("Активные воркеры", html)
        self.assertIn("Доступные вычислительные цели", html)
        self.assertIn("Reported / наблюдаемая нагрузка", html)
        self.assertIn("workersSectionNote", html)
        self.assertIn("targetsSectionNote", html)
        self.assertIn("/api/admin/dashboard/summary", html)
        self.assertNotIn("Что происходит с мощностью и очередями прямо сейчас", html)


if __name__ == "__main__":
    unittest.main()

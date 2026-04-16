import json
import os
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from jose import jwt
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
import auth_kerberos as auth_module


class FakeLimiter:
    async def check(self, _subject):
        return None


class FakeGateway:
    def __init__(self):
        self.redis = None

    async def get_model_catalog(self):
        return {
            "phi3:mini": {
                "name": "phi3:mini",
                "description": "Mini model",
                "size": "1",
                "status": "active",
            }
        }


class FakeDashboardRedis:
    async def ping(self):
        return True


class FakeDashboardGateway:
    def __init__(self):
        self.redis = FakeDashboardRedis()

    async def get_scheduler_status(self):
        return {"last_seen": 1_800_000_000}

    async def list_active_workers(self):
        return []

    async def list_working_workers(self, _workload_class=None):
        return []

    async def can_accept_workload(self, _workload_class=None):
        return True

    async def get_runtime_state(self):
        return {"pending": {}, "active_jobs": 0, "targets": 0, "workers": 0}

    async def get_basic_metrics(self):
        return {
            "queue_depth": 0,
            "active_jobs": 0,
            "failed_jobs": 0,
            "rejected_jobs": 0,
            "job_latency_total_ms": 0,
            "job_latency_count": 0,
        }

    async def list_active_targets(self):
        return []


class LabOpenAuthModeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def extract_cookie_value(response, cookie_name: str) -> str | None:
        prefix = f"{cookie_name}="
        for header, value in response.raw_headers:
            if header.lower() != b"set-cookie":
                continue
            decoded = value.decode("utf-8", errors="ignore")
            if decoded.startswith(prefix):
                return decoded.split(";", 1)[0].split("=", 1)[1].strip('"')
        return None

    @staticmethod
    def build_template_request(path: str) -> Request:
        app = FastAPI()
        app.state.llm_gateway = FakeGateway()
        app.state.chat_store = types.SimpleNamespace(get_history=AsyncMock(return_value=[]))
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": path,
                "raw_path": path.encode("utf-8"),
                "query_string": b"",
                "headers": [(b"host", b"assistant.local")],
                "client": ("127.0.0.1", 12345),
                "server": ("assistant.local", 443),
                "app": app,
            }
        )

    @staticmethod
    def build_login_request():
        return types.SimpleNamespace(
            cookies={},
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(
                    login_rate_limiter=FakeLimiter(),
                    llm_gateway=FakeGateway(),
                )
            ),
        )

    async def test_login_page_renders_lab_warning(self):
        request = self.build_template_request("/login")

        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ):
            response = await app_module.login_page(request, current_user=None)

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Открыть LAB", html)
        self.assertIn("Небезопасный lab profile", html)

    async def test_lab_open_login_redirects_without_calling_kerberos(self):
        request = self.build_login_request()

        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ), patch.object(app_module.settings, "LAB_USER_USERNAME", "lab_user"), patch.object(
            app_module.settings, "LAB_USER_CANONICAL_PRINCIPAL", "lab_user@LOCAL.LAB"
        ), patch.object(
            app_module.settings, "DEFAULT_MODEL", "phi3:mini"
        ), patch.object(
            app_module.kerberos_auth,
            "authenticate",
            side_effect=AssertionError("Kerberos auth must not be called in lab_open mode"),
        ):
            response = await app_module.login(request, username="ignored", password="ignored")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/chat")
        access_cookie = self.extract_cookie_value(response, "access_token")
        self.assertIsNotNone(access_cookie)

        token = access_cookie.replace("Bearer%20", "").replace("Bearer ", "")
        payload = jwt.decode(token, app_module.settings.SECRET_KEY, algorithms=[app_module.settings.ALGORITHM])
        self.assertEqual(payload["sub"], "lab_user")
        self.assertEqual(payload["auth_source"], "lab_open")

    async def test_api_user_returns_synthetic_lab_identity_without_session(self):
        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ), patch.object(app_module.settings, "LAB_USER_USERNAME", "lab_user"), patch.object(
            app_module.settings, "LAB_USER_CANONICAL_PRINCIPAL", "lab_user@LOCAL.LAB"
        ):
            current_user = await auth_module.get_current_user_required(current_user=None)
            response = await app_module.api_user(current_user=current_user)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["username"], "lab_user")
        self.assertEqual(payload["canonical_principal"], "lab_user@LOCAL.LAB")
        self.assertEqual(payload["groups"], [])
        self.assertEqual(payload["auth_source"], "lab_open")

    async def test_dashboard_summary_allows_lab_open_identity(self):
        app = FastAPI()
        app.state.llm_gateway = FakeDashboardGateway()
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/admin/dashboard/summary",
                "headers": [],
                "query_string": b"",
                "app": app,
            }
        )

        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ):
            current_user = await app_module.get_admin_dashboard_identity_required(
                request,
                current_user=None,
                current_local_admin=None,
            )
            response = await app_module.get_admin_dashboard_summary(request, current_user=current_user)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(current_user["dashboard_auth_mode"], "lab_open")
        self.assertEqual(payload["current_user"], "lab_user")

    async def test_dashboard_route_renders_lab_warning_banner(self):
        request = self.build_template_request("/admin/dashboard")

        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ), patch.object(app_module.settings, "LAB_USER_USERNAME", "lab_user"):
            current_user = await app_module.get_admin_dashboard_identity_required(
                request,
                current_user=None,
                current_local_admin=None,
            )
            response = await app_module.admin_dashboard_page(request, current_user=current_user)

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("WARNING: standalone GPU lab mode", html)
        self.assertIn("lab_user", html)

    def test_trusted_proxy_sso_is_disabled_when_lab_open_enabled(self):
        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ), patch.object(app_module.settings, "SSO_ENABLED", True), patch.object(
            app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True
        ):
            self.assertFalse(app_module.trusted_proxy_sso_enabled())

    async def test_chat_page_sets_lab_session_cookies_for_direct_open(self):
        app = FastAPI()
        app.state.llm_gateway = FakeGateway()
        app.state.chat_store = types.SimpleNamespace(get_history=AsyncMock(return_value=[]))
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/chat",
                "raw_path": b"/chat",
                "query_string": b"",
                "headers": [(b"host", b"assistant.local")],
                "client": ("127.0.0.1", 12345),
                "server": ("assistant.local", 443),
                "app": app,
            }
        )

        with patch.object(app_module.settings, "AUTH_MODE", "lab_open"), patch.object(
            app_module.settings, "LAB_OPEN_AUTH_ACK", True
        ), patch.object(
            app_module,
            "build_conversation_writer",
            return_value=object(),
        ), patch.object(
            app_module,
            "load_thread_summaries",
            AsyncMock(return_value=[{"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 0}]),
        ), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "phi3:mini", "name": "phi3:mini", "description": "Mini model"}),
        ):
            response = await app_module.chat_page(
                request,
                thread_id=None,
                current_user=await auth_module.get_current_user_required(current_user=None),
            )

        set_cookie_headers = [
            value.decode("utf-8", errors="ignore")
            for header, value in response.raw_headers
            if header.lower() == b"set-cookie"
        ]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(header.startswith("access_token=") for header in set_cookie_headers))
        self.assertTrue(any(header.startswith("csrf_token=") for header in set_cookie_headers))


if __name__ == "__main__":
    unittest.main()

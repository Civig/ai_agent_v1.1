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
from local_admin_security import build_local_admin_password_hash


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


class StandaloneChatAuthModeTests(unittest.IsolatedAsyncioTestCase):
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
    def build_request(path: str, method: str = "GET") -> Request:
        app = FastAPI()
        app.state.llm_gateway = FakeGateway()
        app.state.login_rate_limiter = FakeLimiter()
        app.state.chat_store = types.SimpleNamespace(get_history=AsyncMock(return_value=[]))
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": method,
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

    async def test_login_page_renders_demo_test_warning_only_when_standalone_auth_enabled(self):
        request = self.build_request("/login")
        password_hash = build_local_admin_password_hash("StandaloneTestPassword-123")

        with patch.object(app_module.settings, "STANDALONE_CHAT_AUTH_ENABLED", True), patch.object(
            app_module.settings, "STANDALONE_CHAT_USERNAME", "demo_ai"
        ), patch.object(app_module.settings, "STANDALONE_CHAT_PASSWORD_HASH", password_hash):
            response = await app_module.login_page(request, current_user=None)

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Включён demo/test chat login", html)
        self.assertIn("demo_ai", html)
        self.assertNotIn("Открыть LAB", html)

    async def test_standalone_chat_login_redirects_without_calling_kerberos(self):
        request = self.build_request("/login", method="POST")
        secret = "StandaloneTestPassword-123"
        password_hash = build_local_admin_password_hash(secret)

        with patch.object(app_module.settings, "STANDALONE_CHAT_AUTH_ENABLED", True), patch.object(
            app_module.settings, "STANDALONE_CHAT_USERNAME", "demo_ai"
        ), patch.object(app_module.settings, "STANDALONE_CHAT_PASSWORD_HASH", password_hash), patch.object(
            app_module.kerberos_auth,
            "authenticate",
            side_effect=AssertionError("Kerberos auth must not be called for standalone/test chat login"),
        ), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "phi3:mini", "name": "phi3:mini", "description": "Mini model"}),
        ):
            response = await app_module.login(request, username="demo_ai", password=secret)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/chat")
        access_cookie = self.extract_cookie_value(response, "access_token")
        self.assertIsNotNone(access_cookie)

        token = access_cookie.replace("Bearer%20", "").replace("Bearer ", "")
        payload = jwt.decode(token, app_module.settings.SECRET_KEY, algorithms=[app_module.settings.ALGORITHM])
        self.assertEqual(payload["sub"], "demo_ai")
        self.assertEqual(payload["auth_source"], "password")
        self.assertEqual(payload["canonical_principal"], "demo_ai@STANDALONE.LOCAL")

    async def test_standalone_chat_wrong_password_returns_401_without_kerberos(self):
        request = self.build_request("/login", method="POST")
        password_hash = build_local_admin_password_hash("StandaloneTestPassword-123")

        with patch.object(app_module.settings, "STANDALONE_CHAT_AUTH_ENABLED", True), patch.object(
            app_module.settings, "STANDALONE_CHAT_USERNAME", "demo_ai"
        ), patch.object(app_module.settings, "STANDALONE_CHAT_PASSWORD_HASH", password_hash), patch.object(
            app_module.kerberos_auth,
            "authenticate",
            side_effect=AssertionError("Kerberos auth must not be called after standalone/test password mismatch"),
        ):
            response = await app_module.login(request, username="demo_ai", password="wrong-password")

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Неверное имя пользователя или пароль", html)

    async def test_disabled_standalone_chat_falls_back_to_kerberos(self):
        request = self.build_request("/login", method="POST")
        kerberos_user = {
            "username": "demo_ai",
            "canonical_principal": "demo_ai@EXAMPLE.LOCAL",
            "display_name": "Demo AI",
            "email": "demo_ai@example.local",
            "groups": ["domain_users"],
        }

        with patch.object(app_module.settings, "STANDALONE_CHAT_AUTH_ENABLED", False), patch.object(
            app_module.settings, "STANDALONE_CHAT_USERNAME", "demo_ai"
        ), patch.object(app_module.settings, "STANDALONE_CHAT_PASSWORD_HASH", ""), patch.object(
            app_module.kerberos_auth,
            "authenticate",
            return_value=kerberos_user,
        ) as authenticate_mock, patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "phi3:mini", "name": "phi3:mini", "description": "Mini model"}),
        ):
            response = await app_module.login(request, username="demo_ai", password="KerberosPassword-123")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/chat")
        authenticate_mock.assert_called_once_with("demo_ai", "KerberosPassword-123")

    async def test_nonmatching_username_falls_back_to_kerberos_even_when_standalone_auth_is_enabled(self):
        request = self.build_request("/login", method="POST")
        password_hash = build_local_admin_password_hash("StandaloneTestPassword-123")
        kerberos_user = {
            "username": "alice",
            "canonical_principal": "alice@EXAMPLE.LOCAL",
            "display_name": "Alice",
            "email": "alice@example.local",
            "groups": ["domain_users"],
        }

        with patch.object(app_module.settings, "STANDALONE_CHAT_AUTH_ENABLED", True), patch.object(
            app_module.settings, "STANDALONE_CHAT_USERNAME", "demo_ai"
        ), patch.object(app_module.settings, "STANDALONE_CHAT_PASSWORD_HASH", password_hash), patch.object(
            app_module.kerberos_auth,
            "authenticate",
            return_value=kerberos_user,
        ) as authenticate_mock, patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "phi3:mini", "name": "phi3:mini", "description": "Mini model"}),
        ):
            response = await app_module.login(request, username="alice", password="AlicePassword-123")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/chat")
        authenticate_mock.assert_called_once_with("alice", "AlicePassword-123")


if __name__ == "__main__":
    unittest.main()

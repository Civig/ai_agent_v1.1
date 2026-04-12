import json
import os
import re
import types
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
import auth_kerberos as auth_module
from local_admin_security import build_local_admin_password_hash


class LocalAdminBreakGlassTests(unittest.IsolatedAsyncioTestCase):
    class FakeRedis:
        def __init__(self):
            self.storage = {}

        async def get(self, key):
            return self.storage.get(key)

        async def set(self, key, value, ex=None):
            self.storage[key] = value

        async def exists(self, key):
            return 1 if key in self.storage else 0

    class FakeLimiter:
        async def check(self, subject):
            return None

    class FakeGateway:
        def __init__(self):
            self.redis = LocalAdminBreakGlassTests.FakeRedis()

        async def get_scheduler_status(self):
            return None

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

    @staticmethod
    def make_request(*, path, method="GET", cookies=None, headers=None, app_state=None):
        raw_headers = [(b"host", b"testserver")]
        for key, value in (headers or {}).items():
            raw_headers.append((key.lower().encode("utf-8"), str(value).encode("utf-8")))
        if cookies:
            cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
            raw_headers.append((b"cookie", cookie_header.encode("utf-8")))

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": raw_headers,
            "query_string": b"",
            "scheme": "https",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
            "app": types.SimpleNamespace(state=app_state),
        }
        return Request(scope)

    @staticmethod
    def extract_cookie_value(response, cookie_name):
        cookie_jar = LocalAdminBreakGlassTests.build_cookie_jar(response)
        matches = [(path, value) for (name, path), value in cookie_jar.items() if name == cookie_name]
        if not matches:
            return None
        matches.sort(key=lambda item: len(item[0]), reverse=True)
        return matches[0][1]

    @staticmethod
    def build_cookie_jar(response):
        jar = {}
        for header, value in response.raw_headers:
            if header.lower() != b"set-cookie":
                continue
            parsed = SimpleCookie()
            parsed.load(value.decode("utf-8", errors="ignore"))
            for morsel in parsed.values():
                cookie_path = morsel["path"] or "/"
                max_age = (morsel["max-age"] or "").strip()
                expires = (morsel["expires"] or "").strip().lower()
                is_deleted = max_age == "0" or expires.startswith("thu, 01 jan 1970")
                key = (morsel.key, cookie_path)
                if is_deleted:
                    jar.pop(key, None)
                    continue
                jar[key] = morsel.value
        return jar

    @staticmethod
    def cookies_for_path(cookie_jar, path):
        selected = {}
        for (name, cookie_path), value in cookie_jar.items():
            normalized_cookie_path = cookie_path or "/"
            if normalized_cookie_path != "/" and not path.startswith(normalized_cookie_path):
                continue
            current = selected.get(name)
            if current is None or len(normalized_cookie_path) >= len(current[0]):
                selected[name] = (normalized_cookie_path, value)
        return {name: value for name, (_, value) in selected.items()}

    def make_app_state(self):
        return types.SimpleNamespace(
            llm_gateway=self.FakeGateway(),
            login_rate_limiter=self.FakeLimiter(),
        )

    async def test_local_admin_disabled_by_default_route_is_not_configured(self):
        request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, app_state=self.make_app_state())

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", False), patch.object(
            app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", ""
        ):
            with self.assertRaises(HTTPException) as error:
                await app_module.local_admin_login_page(request)

        self.assertEqual(error.exception.status_code, 404)

    async def test_ad_dashboard_path_still_works_with_existing_allowlist(self):
        request = self.make_request(path="/admin/dashboard", app_state=self.make_app_state())
        current_user = {"username": "alice", "display_name": "Alice", "email": "alice@corp.local"}

        with patch.object(app_module.settings, "ADMIN_DASHBOARD_USERS", "alice"):
            app_module.parse_admin_dashboard_allowed_users.cache_clear()
            identity = await app_module.get_admin_dashboard_identity_required(
                request,
                current_user=current_user,
                current_local_admin=None,
            )

        self.assertEqual(identity["dashboard_auth_mode"], "ad")
        self.assertEqual(identity["logout_path"], "/logout")

    async def test_bootstrap_secret_login_redirects_to_rotation_and_dashboard_stays_denied(self):
        app_state = self.make_app_state()
        bootstrap_secret = "bootstrap-secret-for-local-admin-1234"
        password_hash = build_local_admin_password_hash(bootstrap_secret)
        login_request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", True
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", True
        ):
            response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=bootstrap_secret,
            )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], app_module.LOCAL_ADMIN_ROTATE_PATH)

            access_cookie = self.extract_cookie_value(response, app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME)
            csrf_cookie = self.extract_cookie_value(response, app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME)
            session_request = self.make_request(
                path="/admin/dashboard",
                cookies={
                    app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME: access_cookie,
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME: csrf_cookie,
                },
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(session_request)

            self.assertTrue(current_local_admin["rotation_required"])
            with self.assertRaises(HTTPException) as error:
                await app_module.get_admin_dashboard_identity_required(
                    session_request,
                    current_user=None,
                    current_local_admin=current_local_admin,
                )

        self.assertEqual(error.exception.status_code, 403)

    async def test_compose_safe_bootstrap_hash_still_allows_rotation_login(self):
        app_state = self.make_app_state()
        bootstrap_secret = "bootstrap-secret-compose-safe-1234"
        password_hash = build_local_admin_password_hash(bootstrap_secret).replace("$", "$$")
        login_request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", True
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", True
        ):
            response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=bootstrap_secret,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], app_module.LOCAL_ADMIN_ROTATE_PATH)

    async def test_rotation_invalidates_bootstrap_secret_and_allows_dashboard_with_new_password(self):
        app_state = self.make_app_state()
        bootstrap_secret = "bootstrap-secret-for-local-admin-5678"
        new_password = "VeryLongNewLocalAdminPassword-123"
        password_hash = build_local_admin_password_hash(bootstrap_secret)
        login_request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", True
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", True
        ):
            login_response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=bootstrap_secret,
            )
            old_access_cookie = self.extract_cookie_value(login_response, app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME)
            csrf_cookie = self.extract_cookie_value(login_response, app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME)

            rotate_request = self.make_request(
                path=app_module.LOCAL_ADMIN_ROTATE_PATH,
                method="POST",
                cookies={
                    app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME: old_access_cookie,
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME: csrf_cookie,
                },
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(rotate_request)
            rotate_response = await app_module.local_admin_rotate_password(
                rotate_request,
                new_password=new_password,
                confirm_password=new_password,
                csrf_token=csrf_cookie,
                current_local_admin=current_local_admin,
            )
            rotated_cookie_jar = self.build_cookie_jar(rotate_response)
            dashboard_cookies = self.cookies_for_path(rotated_cookie_jar, "/admin/dashboard")
            api_cookies = self.cookies_for_path(rotated_cookie_jar, "/api/admin/dashboard/summary")

            self.assertEqual(rotate_response.status_code, 303)
            self.assertEqual(rotate_response.headers["location"], "/admin/dashboard")
            self.assertIn(app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME, dashboard_cookies)
            self.assertIn(app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME, api_cookies)

            stored_state = json.loads(app_state.llm_gateway.redis.storage[app_module.LOCAL_ADMIN_STATE_REDIS_KEY])
            self.assertFalse(stored_state["force_rotate"])
            self.assertFalse(stored_state["bootstrap_required"])
            self.assertTrue(stored_state["runtime_override"])

            old_session_request = self.make_request(
                path="/admin/dashboard",
                cookies={app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME: old_access_cookie},
                app_state=app_state,
            )
            self.assertIsNone(await app_module.get_current_local_admin_session(old_session_request))

            dashboard_request = self.make_request(
                path="/admin/dashboard",
                cookies=dashboard_cookies,
                app_state=app_state,
            )
            dashboard_local_admin = await app_module.get_current_local_admin_session(dashboard_request)
            dashboard_identity = await app_module.get_admin_dashboard_identity_required(
                dashboard_request,
                current_user=None,
                current_local_admin=dashboard_local_admin,
            )

            api_request = self.make_request(
                path="/api/admin/dashboard/summary",
                cookies=api_cookies,
                app_state=app_state,
            )
            api_local_admin = await app_module.get_current_local_admin_session(api_request)
            api_response = await app_module.get_admin_dashboard_summary(
                api_request,
                current_user=await app_module.get_admin_dashboard_identity_required(
                    api_request,
                    current_user=None,
                    current_local_admin=api_local_admin,
                ),
            )

            failed_login = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=bootstrap_secret,
            )
            self.assertEqual(failed_login.status_code, 401)

            success_login = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=new_password,
            )
            self.assertEqual(success_login.status_code, 303)
            self.assertEqual(success_login.headers["location"], "/admin/dashboard")

            new_access_cookie = self.extract_cookie_value(success_login, app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME)
            second_dashboard_request = self.make_request(
                path="/admin/dashboard",
                cookies={app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME: new_access_cookie},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(second_dashboard_request)
            identity = await app_module.get_admin_dashboard_identity_required(
                second_dashboard_request,
                current_user=None,
                current_local_admin=current_local_admin,
            )

        api_payload = json.loads(api_response.body)
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_payload["current_user"], "admin_ai")
        self.assertEqual(dashboard_identity["dashboard_auth_mode"], "local_admin")
        self.assertEqual(identity["dashboard_auth_mode"], "local_admin")
        self.assertEqual(identity["logout_path"], app_module.LOCAL_ADMIN_LOGOUT_PATH)

    async def test_wrong_local_admin_password_is_denied(self):
        app_state = self.make_app_state()
        password_hash = build_local_admin_password_hash("CorrectLocalAdminPassword-123")
        request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            response = await app_module.local_admin_login(
                request,
                username="admin_ai",
                password="wrong-password",
            )

        self.assertEqual(response.status_code, 401)

    async def test_local_admin_session_does_not_become_regular_chat_user_session(self):
        app_state = self.make_app_state()
        local_admin_password = "LocalAdminPasswordForDashboardOnly-123"
        password_hash = build_local_admin_password_hash(local_admin_password)
        login_request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=local_admin_password,
            )
            browser_cookies = self.cookies_for_path(self.build_cookie_jar(response), "/api/user")
            self.assertIn(app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME, browser_cookies)
            request = self.make_request(
                path="/api/user",
                cookies=browser_cookies,
                app_state=app_state,
            )
            current_user = await auth_module.get_current_user(request, credentials=None)

        self.assertIsNone(current_user)

    async def test_local_admin_logout_revokes_session_and_clears_cookies(self):
        app_state = self.make_app_state()
        local_admin_password = "LocalAdminPasswordForLogout-123"
        password_hash = build_local_admin_password_hash(local_admin_password)
        login_request = self.make_request(path=app_module.LOCAL_ADMIN_LOGIN_PATH, method="POST", app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            login_response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=local_admin_password,
            )
            login_cookie_jar = self.build_cookie_jar(login_response)
            logout_cookies = self.cookies_for_path(login_cookie_jar, app_module.LOCAL_ADMIN_LOGOUT_PATH)
            dashboard_cookies = self.cookies_for_path(login_cookie_jar, "/admin/dashboard")
            api_cookies = self.cookies_for_path(login_cookie_jar, "/api/admin/dashboard/summary")
            csrf_cookie = logout_cookies[app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME]
            logout_request = self.make_request(
                path=app_module.LOCAL_ADMIN_LOGOUT_PATH,
                method="POST",
                cookies=logout_cookies,
                headers={"x-csrf-token": csrf_cookie, "origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(logout_request)
            response = await app_module.local_admin_logout(logout_request, current_local_admin=current_local_admin)

            route_after_logout = self.make_request(
                path="/admin/dashboard",
                cookies=dashboard_cookies,
                app_state=app_state,
            )
            route_local_admin = await app_module.get_current_local_admin_session(route_after_logout)

            api_after_logout = self.make_request(
                path="/api/admin/dashboard/summary",
                cookies=api_cookies,
                app_state=app_state,
            )
            api_local_admin = await app_module.get_current_local_admin_session(api_after_logout)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(route_local_admin)
        self.assertIsNone(api_local_admin)
        deleted_cookie_headers = [
            value.decode("utf-8", errors="ignore")
            for header, value in response.raw_headers
            if header.lower() == b"set-cookie"
        ]
        self.assertTrue(any(header.startswith(f"{app_module.LOCAL_ADMIN_ACCESS_COOKIE_NAME}=") for header in deleted_cookie_headers))
        self.assertTrue(any(header.startswith(f"{app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME}=") for header in deleted_cookie_headers))
        self.assertTrue(any("Path=/" in header for header in deleted_cookie_headers))
        self.assertTrue(any("Path=/admin" in header for header in deleted_cookie_headers))
        with self.assertRaises(HTTPException) as route_error:
            await app_module.get_admin_dashboard_identity_required(
                route_after_logout,
                current_user=None,
                current_local_admin=route_local_admin,
            )
        with self.assertRaises(HTTPException) as api_error:
            await app_module.get_admin_dashboard_identity_required(
                api_after_logout,
                current_user=None,
                current_local_admin=api_local_admin,
            )
        self.assertEqual(route_error.exception.status_code, 403)
        self.assertEqual(api_error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

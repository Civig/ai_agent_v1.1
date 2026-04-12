import json
import os
import types
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
import auth_kerberos as auth_module
from local_admin_security import build_local_admin_password_hash


class LocalAdminChangePasswordTests(unittest.IsolatedAsyncioTestCase):
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
        def __init__(self):
            self.subjects = []

        async def check(self, subject):
            self.subjects.append(subject)
            return None

    class FakeGateway:
        def __init__(self):
            self.redis = LocalAdminChangePasswordTests.FakeRedis()

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

    def make_app_state(self):
        return types.SimpleNamespace(
            llm_gateway=self.FakeGateway(),
            login_rate_limiter=self.FakeLimiter(),
        )

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

    async def login_local_admin(
        self,
        *,
        app_state,
        password_hash,
        password,
        force_rotate=False,
        bootstrap_required=False,
    ):
        login_request = self.make_request(
            path=app_module.LOCAL_ADMIN_LOGIN_PATH,
            method="POST",
            app_state=app_state,
        )
        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", force_rotate
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", bootstrap_required
        ):
            response = await app_module.local_admin_login(
                login_request,
                username="admin_ai",
                password=password,
            )
        return response, self.build_cookie_jar(response)

    async def authenticate_local_admin_without_rotation(self, *, app_state, password):
        password_hash = build_local_admin_password_hash(password)
        response, cookie_jar = await self.login_local_admin(
            app_state=app_state,
            password_hash=password_hash,
            password=password,
            force_rotate=False,
            bootstrap_required=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/dashboard")
        return cookie_jar, password_hash

    async def test_authenticated_local_admin_get_change_password_page_returns_200(self):
        app_state = self.make_app_state()
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password="LocalAdminCurrentPassword-123",
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password_page(
                request,
                current_local_admin=current_local_admin,
            )

        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Смена пароля local break-glass admin", html)
        self.assertIn("name=\"current_password\"", html)
        self.assertIn("name=\"confirm_new_password\"", html)

    async def test_anonymous_get_change_password_is_denied(self):
        app_state = self.make_app_state()
        request = self.make_request(path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH, app_state=app_state)

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", build_local_admin_password_hash("LocalAdminPassword-123")
        ), patch.object(app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"):
            with self.assertRaises(HTTPException) as error:
                await app_module.get_current_local_admin_session_required(request, current_local_admin=None)

        self.assertEqual(error.exception.status_code, 401)

    async def test_ordinary_ad_cookie_get_change_password_is_denied(self):
        app_state = self.make_app_state()
        access_token = app_module.create_access_token(
            app_module.build_token_payload(
                {
                    "username": "alice",
                    "display_name": "Alice",
                    "email": "alice@corp.local",
                    "model": "phi3:mini",
                    "model_key": "phi3:mini",
                    "model_description": "Модель по умолчанию",
                },
                "access",
            )
        )
        request = self.make_request(
            path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
            cookies={"access_token": f"Bearer {access_token}"},
            app_state=app_state,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", build_local_admin_password_hash("LocalAdminPassword-123")
        ), patch.object(app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"):
            current_local_admin = await app_module.get_current_local_admin_session(request)
            self.assertIsNone(current_local_admin)
            with self.assertRaises(HTTPException) as error:
                await app_module.get_current_local_admin_session_required(request, current_local_admin=current_local_admin)

        self.assertEqual(error.exception.status_code, 401)

    async def test_pending_rotation_local_admin_cannot_bypass_normal_change_password_flow(self):
        app_state = self.make_app_state()
        bootstrap_secret = "BootstrapSecretForPendingRotation-123"
        password_hash = build_local_admin_password_hash(bootstrap_secret)
        _, cookie_jar = await self.login_local_admin(
            app_state=app_state,
            password_hash=password_hash,
            password=bootstrap_secret,
            force_rotate=True,
            bootstrap_required=True,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", True
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", True
        ):
            get_request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(get_request)
            response = await app_module.local_admin_change_password_page(
                get_request,
                current_local_admin=current_local_admin,
            )

            post_request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(post_request)
            with self.assertRaises(HTTPException) as error:
                await app_module.local_admin_change_password(
                    post_request,
                    current_password=bootstrap_secret,
                    new_password="VeryLongPendingRotationPassword-123",
                    confirm_new_password="VeryLongPendingRotationPassword-123",
                    csrf_token=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)[
                        app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME
                    ],
                    current_local_admin=current_local_admin,
                )

        self.assertIsInstance(response, RedirectResponse)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], app_module.LOCAL_ADMIN_ROTATE_PATH)
        self.assertEqual(error.exception.status_code, 403)

    async def test_wrong_current_password_is_rejected_and_logged(self):
        app_state = self.make_app_state()
        current_password = "LocalAdminCurrentPassword-123"
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password=current_password,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ), self.assertLogs("app", level="WARNING") as logs:
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password(
                request,
                current_password="WrongCurrentPassword-123",
                new_password="VeryLongReplacementPassword-123",
                confirm_new_password="VeryLongReplacementPassword-123",
                csrf_token=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)[
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME
                ],
                current_local_admin=current_local_admin,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Текущий пароль указан неверно.", response.body.decode("utf-8"))
        self.assertTrue(any("reason=current_password_mismatch" in line for line in logs.output))

    async def test_confirm_mismatch_is_rejected(self):
        app_state = self.make_app_state()
        current_password = "LocalAdminCurrentPassword-123"
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password=current_password,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password(
                request,
                current_password=current_password,
                new_password="VeryLongReplacementPassword-123",
                confirm_new_password="MismatchReplacementPassword-123",
                csrf_token=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)[
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME
                ],
                current_local_admin=current_local_admin,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Подтверждение нового пароля не совпадает.", response.body.decode("utf-8"))

    async def test_same_as_current_password_is_rejected(self):
        app_state = self.make_app_state()
        current_password = "LocalAdminCurrentPassword-123"
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password=current_password,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password(
                request,
                current_password=current_password,
                new_password=current_password,
                confirm_new_password=current_password,
                csrf_token=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)[
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME
                ],
                current_local_admin=current_local_admin,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Новый пароль должен отличаться от текущего.", response.body.decode("utf-8"))

    async def test_too_short_new_password_is_rejected(self):
        app_state = self.make_app_state()
        current_password = "LocalAdminCurrentPassword-123"
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password=current_password,
        )

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH),
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password(
                request,
                current_password=current_password,
                new_password="too-short",
                confirm_new_password="too-short",
                csrf_token=self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)[
                    app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME
                ],
                current_local_admin=current_local_admin,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Новый пароль должен быть не короче 16 символов.", response.body.decode("utf-8"))

    async def test_successful_password_change_invalidates_old_session_and_requires_fresh_login(self):
        app_state = self.make_app_state()
        old_password = "LocalAdminCurrentPassword-123"
        new_password = "LocalAdminReplacementPassword-456"
        cookie_jar, password_hash = await self.authenticate_local_admin_without_rotation(
            app_state=app_state,
            password=old_password,
        )
        old_change_cookies = self.cookies_for_path(cookie_jar, app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH)
        old_dashboard_cookies = self.cookies_for_path(cookie_jar, "/admin/dashboard")
        old_api_cookies = self.cookies_for_path(cookie_jar, "/api/admin/dashboard/summary")

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ), self.assertLogs("app", level="INFO") as logs:
            request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                method="POST",
                cookies=old_change_cookies,
                headers={"origin": "https://testserver"},
                app_state=app_state,
            )
            current_local_admin = await app_module.get_current_local_admin_session(request)
            response = await app_module.local_admin_change_password(
                request,
                current_password=old_password,
                new_password=new_password,
                confirm_new_password=new_password,
                csrf_token=old_change_cookies[app_module.LOCAL_ADMIN_CSRF_COOKIE_NAME],
                current_local_admin=current_local_admin,
            )

            old_login_response, _ = await self.login_local_admin(
                app_state=app_state,
                password_hash=password_hash,
                password=old_password,
                force_rotate=False,
                bootstrap_required=False,
            )

            new_login_request = self.make_request(
                path=app_module.LOCAL_ADMIN_LOGIN_PATH,
                method="POST",
                app_state=app_state,
            )
            new_login_response = await app_module.local_admin_login(
                new_login_request,
                username="admin_ai",
                password=new_password,
            )
            fresh_cookie_jar = self.build_cookie_jar(new_login_response)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"{app_module.LOCAL_ADMIN_LOGIN_PATH}?password_changed=1")
        self.assertEqual(old_login_response.status_code, 401)
        self.assertEqual(new_login_response.status_code, 303)
        self.assertEqual(new_login_response.headers["location"], "/admin/dashboard")
        self.assertTrue(any("password change succeeded" in line for line in logs.output))

        with patch.object(app_module.settings, "LOCAL_ADMIN_ENABLED", True), patch.object(
            app_module.settings, "LOCAL_ADMIN_USERNAME", "admin_ai"
        ), patch.object(app_module.settings, "LOCAL_ADMIN_PASSWORD_HASH", password_hash), patch.object(
            app_module.settings, "LOCAL_ADMIN_FORCE_ROTATE", False
        ), patch.object(
            app_module.settings, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED", False
        ):
            old_route_request = self.make_request(
                path="/admin/dashboard",
                cookies=old_dashboard_cookies,
                app_state=app_state,
            )
            old_route_session = await app_module.get_current_local_admin_session(old_route_request)
            self.assertIsNone(old_route_session)
            with self.assertRaises(HTTPException) as route_error:
                await app_module.get_admin_dashboard_identity_required(
                    old_route_request,
                    current_user=None,
                    current_local_admin=old_route_session,
                )

            old_api_request = self.make_request(
                path="/api/admin/dashboard/summary",
                cookies=old_api_cookies,
                app_state=app_state,
            )
            old_api_session = await app_module.get_current_local_admin_session(old_api_request)
            self.assertIsNone(old_api_session)
            with self.assertRaises(HTTPException) as api_error:
                await app_module.get_admin_dashboard_identity_required(
                    old_api_request,
                    current_user=None,
                    current_local_admin=old_api_session,
                )

            old_change_request = self.make_request(
                path=app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH,
                cookies=old_change_cookies,
                app_state=app_state,
            )
            old_change_session = await app_module.get_current_local_admin_session(old_change_request)
            self.assertIsNone(old_change_session)
            with self.assertRaises(HTTPException) as change_error:
                await app_module.get_current_local_admin_session_required(
                    old_change_request,
                    current_local_admin=old_change_session,
                )

            fresh_dashboard_request = self.make_request(
                path="/admin/dashboard",
                cookies=self.cookies_for_path(fresh_cookie_jar, "/admin/dashboard"),
                app_state=app_state,
            )
            fresh_dashboard_session = await app_module.get_current_local_admin_session(fresh_dashboard_request)
            fresh_dashboard_identity = await app_module.get_admin_dashboard_identity_required(
                fresh_dashboard_request,
                current_user=None,
                current_local_admin=fresh_dashboard_session,
            )
            fresh_dashboard_response = await app_module.admin_dashboard_page(
                fresh_dashboard_request,
                current_user=fresh_dashboard_identity,
            )

            fresh_api_request = self.make_request(
                path="/api/admin/dashboard/summary",
                cookies=self.cookies_for_path(fresh_cookie_jar, "/api/admin/dashboard/summary"),
                app_state=app_state,
            )
            fresh_api_session = await app_module.get_current_local_admin_session(fresh_api_request)
            fresh_api_identity = await app_module.get_admin_dashboard_identity_required(
                fresh_api_request,
                current_user=None,
                current_local_admin=fresh_api_session,
            )
            fresh_api_response = await app_module.get_admin_dashboard_summary(
                fresh_api_request,
                current_user=fresh_api_identity,
            )

            login_page_request = self.make_request(
                path=app_module.LOCAL_ADMIN_LOGIN_PATH,
                app_state=app_state,
            )
            login_page_request.scope["query_string"] = b"password_changed=1"
            login_page_response = await app_module.local_admin_login_page(login_page_request, current_local_admin=None)

            api_user_request = self.make_request(
                path="/api/user",
                cookies=self.cookies_for_path(fresh_cookie_jar, "/api/user"),
                app_state=app_state,
            )
            ordinary_user = await auth_module.get_current_user(api_user_request, credentials=None)

        self.assertEqual(route_error.exception.status_code, 403)
        self.assertEqual(api_error.exception.status_code, 403)
        self.assertEqual(change_error.exception.status_code, 401)
        self.assertEqual(fresh_dashboard_response.status_code, 200)
        self.assertEqual(fresh_api_response.status_code, 200)
        self.assertIn(app_module.LOCAL_ADMIN_PASSWORD_CHANGED_MESSAGE, login_page_response.body.decode("utf-8"))
        self.assertIsNone(ordinary_user)

    async def test_local_admin_dashboard_shell_shows_change_password_control_only_for_local_admin(self):
        app_state = self.make_app_state()
        request = self.make_request(path="/admin/dashboard", app_state=app_state)

        local_admin_response = await app_module.admin_dashboard_page(
            request,
            current_user=app_module.build_local_admin_dashboard_identity(
                {
                    "username": "admin_ai",
                    "display_name": "admin_ai",
                    "email": "break-glass admin",
                    "dashboard_auth_mode": "local_admin",
                }
            ),
        )
        local_admin_html = local_admin_response.body.decode("utf-8")

        ad_response = await app_module.admin_dashboard_page(
            request,
            current_user={
                "username": "alice",
                "display_name": "Alice",
                "email": "alice@corp.local",
                "dashboard_auth_mode": "ad",
            },
        )
        ad_html = ad_response.body.decode("utf-8")

        self.assertIn(app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH, local_admin_html)
        self.assertNotIn(app_module.LOCAL_ADMIN_CHANGE_PASSWORD_PATH, ad_html)


if __name__ == "__main__":
    unittest.main()

import os
import re
import tempfile
import types
import unittest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
import auth_kerberos as auth_module
import config as config_module
import sso_proxy_auth as sso_proxy_module


class AuthSsoPreparationTests(unittest.IsolatedAsyncioTestCase):
    class FakeRedis:
        def __init__(self):
            self.storage = {}

        async def set(self, key, value, ex=None):
            self.storage[key] = value

        async def exists(self, key):
            return 1 if key in self.storage else 0

    @staticmethod
    def make_request(*, headers=None, cookies=None, method="GET", path="/", app_state=None, client_host="127.0.0.1"):
        return types.SimpleNamespace(
            headers=headers or {},
            cookies=cookies or {},
            method=method,
            url=types.SimpleNamespace(scheme="https", path=path),
            client=types.SimpleNamespace(host=client_host),
            app=types.SimpleNamespace(
                state=app_state or types.SimpleNamespace(llm_gateway=types.SimpleNamespace(redis=None))
            ),
        )

    @staticmethod
    def extract_cookie_value(response, cookie_name):
        pattern = re.compile(rf"{cookie_name}=([^;]+)")
        for header, value in response.raw_headers:
            if header.lower() != b"set-cookie":
                continue
            decoded = value.decode("utf-8", errors="ignore")
            match = pattern.search(decoded)
            if match:
                return match.group(1).strip('"')
        return None

    @staticmethod
    def get_route_endpoint(fastapi_app, path):
        for route in fastapi_app.routes:
            if getattr(route, "path", None) == path:
                return route.endpoint
        raise AssertionError(f"Route {path} not found")

    @staticmethod
    async def invoke_app(*, path="/", method="GET", headers=None, client_host="127.0.0.1"):
        raw_headers = []
        for header, value in (headers or {}).items():
            raw_headers.append((header.lower().encode("utf-8"), value.encode("utf-8")))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": raw_headers,
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "app": app_module.app,
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app_module.app(scope, receive, send)
        return messages

    @staticmethod
    def write_policy_catalog(root_dir: Path, *, categories=None):
        catalog = categories or {
            "general": {
                "category": "general",
                "display_name": "General-purpose models",
                "enabled": True,
                "models": [{"model_key": "phi3:mini", "display_name": "Phi-3 Mini"}],
            },
            "coding": {
                "category": "coding",
                "display_name": "Coding models",
                "enabled": True,
                "models": [{"model_key": "codellama:13b", "display_name": "Code Llama 13B"}],
            },
            "admin": {
                "category": "admin",
                "display_name": "Admin-tier models",
                "enabled": True,
                "models": [{"model_key": "llama3.1:8b", "display_name": "Llama 3.1 8B"}],
            },
        }
        for category, payload in catalog.items():
            category_dir = root_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            (category_dir / "policy.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_request_uses_bearer_auth_without_session_detects_bearer_only_mode(self):
        request = self.make_request(headers={"authorization": "Bearer abc"}, cookies={})

        self.assertTrue(app_module.request_uses_bearer_auth_without_session(request))

    def test_parse_group_mapping_normalizes_case_trims_and_deduplicates(self):
        parsed = config_module.parse_group_mapping(" Developers , ai-admins,developers, ,AI-ADMINS ")

        self.assertEqual(parsed, ("developers", "ai-admins"))

    def test_settings_group_mapping_defaults_fail_closed(self):
        with patch.object(config_module.settings, "MODEL_ACCESS_CODING_GROUPS", ""), patch.object(
            config_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", ""
        ):
            self.assertEqual(config_module.settings.model_access_coding_groups, ())
            self.assertEqual(config_module.settings.model_access_admin_groups, ())

    def test_request_uses_bearer_auth_without_session_rejects_other_schemes(self):
        request = self.make_request(headers={"authorization": "Negotiate token"}, cookies={})

        self.assertFalse(app_module.request_uses_bearer_auth_without_session(request))

    def test_enforce_csrf_allows_bearer_without_cookie(self):
        request = self.make_request(headers={"authorization": "Bearer abc"}, cookies={})

        app_module.enforce_csrf(request)

    def test_reject_untrusted_auth_proxy_headers_blocks_reserved_headers_by_default(self):
        request = self.make_request(headers={"x-authenticated-user": "alice"})

        with self.assertRaises(HTTPException) as error:
            app_module.reject_untrusted_auth_proxy_headers(request)

        self.assertEqual(error.exception.status_code, 400)

    def test_reject_untrusted_auth_proxy_headers_allows_reserved_headers_only_on_sso_entry_path(self):
        request = self.make_request(
            headers={"x-authenticated-user": "alice"},
            method="GET",
            path="/auth/sso/login",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            app_module.reject_untrusted_auth_proxy_headers(request)

    def test_reject_untrusted_auth_proxy_headers_rejects_reserved_headers_outside_sso_entry_path_even_when_enabled(self):
        request = self.make_request(
            headers={"x-authenticated-user": "alice"},
            method="GET",
            path="/api/user",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"):
            with self.assertRaises(HTTPException) as error:
                app_module.reject_untrusted_auth_proxy_headers(request)

        self.assertEqual(error.exception.status_code, 400)

    def test_reject_untrusted_auth_proxy_headers_rejects_sso_entry_when_source_is_not_trusted(self):
        request = self.make_request(
            headers={"x-authenticated-user": "alice"},
            method="GET",
            path="/auth/sso/login",
            client_host="203.0.113.10",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.reject_untrusted_auth_proxy_headers(request)

        self.assertEqual(error.exception.status_code, 400)

    def test_parse_trusted_proxy_groups_header_rejects_invalid_payload(self):
        with self.assertRaises(HTTPException) as error:
            app_module.parse_trusted_proxy_groups_header('{"groups":["ai-users"]}')

        self.assertEqual(error.exception.status_code, 400)

    def test_build_trusted_proxy_sso_identity_uses_canonical_identity_contract(self):
        request = self.make_request(
            headers={
                "x-authenticated-user": "EXAMPLE\\Alice",
                "x-authenticated-principal": "alice@EXAMPLE.LOCAL",
                "x-authenticated-email": "alice@example.local",
                "x-authenticated-name": "Alice Example",
                "x-authenticated-groups": '["AI_Users","Domain Users"]',
            },
            method="GET",
            path="/auth/sso/login",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            identity = app_module.build_trusted_proxy_sso_identity(request)

        self.assertEqual(identity["username"], "alice")
        self.assertEqual(identity["canonical_principal"], "alice@EXAMPLE.LOCAL")
        self.assertEqual(identity["auth_source"], "sso")
        self.assertEqual(identity["groups"], ["AI_Users", "Domain Users"])

    def test_build_trusted_proxy_sso_identity_rejects_mismatched_username_and_principal(self):
        request = self.make_request(
            headers={
                "x-authenticated-user": "alice",
                "x-authenticated-principal": "bob@EXAMPLE.LOCAL",
            },
            method="GET",
            path="/auth/sso/login",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.build_trusted_proxy_sso_identity(request)

        self.assertEqual(error.exception.status_code, 401)

    def test_build_trusted_proxy_sso_identity_rejects_untrusted_source_even_on_sso_path(self):
        request = self.make_request(
            headers={
                "x-authenticated-user": "alice",
                "x-authenticated-principal": "alice@EXAMPLE.LOCAL",
            },
            method="GET",
            path="/auth/sso/login",
            client_host="203.0.113.10",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            with self.assertRaises(HTTPException) as error:
                app_module.build_trusted_proxy_sso_identity(request)

        self.assertEqual(error.exception.status_code, 400)

    def test_build_login_rate_subject_ignores_spoofed_forwarded_headers_without_trusted_proxy_source(self):
        request = self.make_request(
            headers={"x-forwarded-for": "198.51.100.7", "x-real-ip": "198.51.100.8"},
            client_host="203.0.113.10",
        )

        with patch.object(app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"):
            subject = app_module.build_login_rate_subject(request, "Alice")

        self.assertEqual(subject, "203.0.113.10:alice")

    def test_build_login_rate_subject_uses_forwarded_headers_for_trusted_proxy_source(self):
        request = self.make_request(
            headers={"x-forwarded-for": "198.51.100.7, 127.0.0.1", "x-real-ip": "198.51.100.8"},
            client_host="127.0.0.1",
        )

        with patch.object(app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"):
            subject = app_module.build_login_rate_subject(request, "Alice")

        self.assertEqual(subject, "198.51.100.8:alice")

    def test_load_model_policy_catalog_reads_folder_based_policies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)

            catalog = auth_module.load_model_policy_catalog(policy_root)

        self.assertEqual(sorted(catalog.keys()), ["admin", "coding", "general"])
        self.assertEqual(catalog["general"]["display_name"], "General-purpose models")
        self.assertIn("codellama:13b", catalog["coding"]["models"])

    def test_get_allowed_model_categories_for_user_uses_env_group_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            catalog = auth_module.load_model_policy_catalog(policy_root)

        with patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"), patch.object(
            auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"
        ):
            general_only = auth_module.get_allowed_model_categories_for_user({"groups": ["domain_users"]}, catalog)
            developer = auth_module.get_allowed_model_categories_for_user({"groups": ["ai-developers"]}, catalog)
            admin = auth_module.get_allowed_model_categories_for_user({"groups": ["ai-admins"]}, catalog)

        self.assertEqual(general_only, ["general"])
        self.assertEqual(developer, ["general", "coding"])
        self.assertEqual(admin, ["general", "admin"])

    def test_get_allowed_model_categories_for_user_requires_exact_group_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            catalog = auth_module.load_model_policy_catalog(policy_root)

        with patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "developers"), patch.object(
            auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "project-admin"
        ):
            categories = auth_module.get_allowed_model_categories_for_user(
                {"groups": ["developers-team", "project-admin-reviewers"]},
                catalog,
            )

        self.assertEqual(categories, ["general"])

    def test_get_allowed_model_categories_for_user_allows_both_mapped_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            catalog = auth_module.load_model_policy_catalog(policy_root)

        with patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"), patch.object(
            auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"
        ):
            categories = auth_module.get_allowed_model_categories_for_user(
                {"groups": ["ai-developers", "ai-admins"]},
                catalog,
            )

        self.assertEqual(categories, ["general", "coding", "admin"])

    def test_get_allowed_model_categories_for_user_empty_env_mapping_keeps_only_general(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            catalog = auth_module.load_model_policy_catalog(policy_root)

        with patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", ""), patch.object(
            auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", ""
        ):
            categories = auth_module.get_allowed_model_categories_for_user(
                {"groups": ["ai-developers", "ai-admins"]},
                catalog,
            )

        self.assertEqual(categories, ["general"])

    def test_enforce_csrf_does_not_treat_negotiate_as_bypass(self):
        request = self.make_request(
            headers={
                "authorization": "Negotiate token",
                "host": "assistant.local",
            },
            cookies={},
        )

        with self.assertRaises(HTTPException) as error:
            app_module.enforce_csrf(request)

        self.assertEqual(error.exception.status_code, 403)

    async def test_get_current_user_rejects_non_bearer_authorization_credentials(self):
        request = self.make_request()
        credentials = HTTPAuthorizationCredentials(scheme="Negotiate", credentials="opaque-ticket")

        current_user = await auth_module.get_current_user(request, credentials=credentials)

        self.assertIsNone(current_user)

    async def test_login_sets_password_auth_session_metadata(self):
        gateway = types.SimpleNamespace(get_model_catalog=AsyncMock(return_value={"demo": {"name": "demo", "description": "Demo"}}))
        app_state = types.SimpleNamespace(
            login_rate_limiter=types.SimpleNamespace(check=AsyncMock(return_value=None)),
            llm_gateway=gateway,
        )
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=app_state),
            headers={},
            client=types.SimpleNamespace(host="127.0.0.1"),
        )
        user_info = {
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.local",
            "groups": ["domain_users"],
        }

        with patch.object(app_module, "kerberos_auth") as kerberos_auth_mock, patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo", "description": "Demo"}),
        ):
            kerberos_auth_mock.authenticate.return_value = user_info
            response = await app_module.login(request, username="alice", password="secret")

        self.assertEqual(response.status_code, 303)
        access_cookie = self.extract_cookie_value(response, "access_token")
        refresh_cookie = self.extract_cookie_value(response, "refresh_token")
        self.assertIsNotNone(access_cookie)
        self.assertIsNotNone(refresh_cookie)
        access_payload = auth_module.jwt.decode(
            access_cookie.replace("Bearer ", ""),
            auth_module.settings.SECRET_KEY,
            algorithms=[auth_module.settings.ALGORITHM],
        )
        self.assertEqual(access_payload["auth_source"], "password")
        self.assertEqual(
            access_payload["canonical_principal"],
            f"alice@{auth_module.settings.KERBEROS_REALM.upper()}",
        )

    async def test_sso_login_entry_sets_sso_session_and_revokes_previous_session_tokens(self):
        fake_redis = self.FakeRedis()
        old_user = {
            "username": "bob",
            "display_name": "Bob",
            "email": "bob@example.local",
            "groups": ["domain_users"],
            "model": "demo",
            "model_description": "Demo",
            "model_key": "demo",
            "auth_source": "password",
            "auth_time": 1700000000,
            "directory_checked_at": 1700000000,
            "identity_version": 1,
        }
        old_access = auth_module.create_access_token(app_module.build_token_payload(old_user, "access"))
        old_refresh = auth_module.create_access_token(app_module.build_token_payload(old_user, "refresh"))
        gateway = types.SimpleNamespace(
            redis=fake_redis,
            get_model_catalog=AsyncMock(return_value={"phi3:mini": {"name": "phi3:mini", "description": "General"}}),
        )
        request = self.make_request(
            headers={
                "x-authenticated-user": "aitest",
                "x-authenticated-principal": "aitest@EXAMPLE.LOCAL",
                "x-authenticated-email": "aitest@example.local",
                "x-authenticated-name": "AI Test",
                "x-authenticated-groups": '["AI_Users"]',
            },
            cookies={
                "access_token": f"Bearer {old_access}",
                "refresh_token": f"Bearer {old_refresh}",
            },
            method="GET",
            path="/auth/sso/login",
            app_state=types.SimpleNamespace(llm_gateway=gateway),
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "phi3:mini", "name": "phi3:mini", "description": "General"}),
        ):
            response = await app_module.sso_login_entry(request, current_user=old_user)

        self.assertEqual(response.status_code, 303)
        access_cookie = self.extract_cookie_value(response, "access_token")
        refresh_cookie = self.extract_cookie_value(response, "refresh_token")
        self.assertIsNotNone(access_cookie)
        self.assertIsNotNone(refresh_cookie)
        access_payload = auth_module.jwt.decode(
            access_cookie.replace("Bearer ", ""),
            auth_module.settings.SECRET_KEY,
            algorithms=[auth_module.settings.ALGORITHM],
        )
        self.assertEqual(access_payload["sub"], "aitest")
        self.assertEqual(access_payload["auth_source"], "sso")
        self.assertEqual(access_payload["groups"], ["AI_Users"])

        old_access_payload = auth_module.jwt.decode(
            old_access,
            auth_module.settings.SECRET_KEY,
            algorithms=[auth_module.settings.ALGORITHM],
            options={"verify_exp": False},
        )
        old_refresh_payload = auth_module.jwt.decode(
            old_refresh,
            auth_module.settings.SECRET_KEY,
            algorithms=[auth_module.settings.ALGORITHM],
            options={"verify_exp": False},
        )
        self.assertIn(auth_module.token_revocation_key(old_access_payload["jti"]), fake_redis.storage)
        self.assertIn(auth_module.token_revocation_key(old_refresh_payload["jti"]), fake_redis.storage)

    async def test_sso_login_entry_requires_enabled_trusted_proxy_mode(self):
        request = self.make_request(
            headers={
                "x-authenticated-user": "aitest",
                "x-authenticated-principal": "aitest@EXAMPLE.LOCAL",
            },
            method="GET",
            path="/auth/sso/login",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", False), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            False,
        ):
            with self.assertRaises(HTTPException) as error:
                await app_module.sso_login_entry(request, current_user=None)

        self.assertEqual(error.exception.status_code, 404)

    async def test_sso_login_entry_rejects_untrusted_direct_source(self):
        request = self.make_request(
            headers={
                "x-authenticated-user": "aitest",
                "x-authenticated-principal": "aitest@EXAMPLE.LOCAL",
            },
            method="GET",
            path="/auth/sso/login",
            client_host="203.0.113.10",
        )

        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "SSO_LOGIN_PATH", "/auth/sso/login"), patch.object(
            app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"
        ):
            with self.assertRaises(HTTPException) as error:
                await app_module.sso_login_entry(request, current_user=None)

        self.assertEqual(error.exception.status_code, 400)

    async def test_middleware_returns_clean_400_without_session_for_untrusted_proxy_headers(self):
        with patch.object(app_module.settings, "TRUSTED_AUTH_PROXY_ENABLED", True), patch.object(
            app_module.settings,
            "SSO_ENABLED",
            True,
        ), patch.object(app_module.settings, "TRUSTED_PROXY_SOURCE_CIDRS", "127.0.0.1/32"):
            messages = await self.invoke_app(
                path="/auth/sso/login",
                headers={
                    "x-authenticated-user": "alice",
                    "x-authenticated-principal": "alice@EXAMPLE.LOCAL",
                },
                client_host="203.0.113.10",
            )

        start_message = next(message for message in messages if message["type"] == "http.response.start")
        body_message = next(message for message in messages if message["type"] == "http.response.body")
        header_map = {key.lower(): value for key, value in start_message["headers"]}

        self.assertEqual(start_message["status"], 400)
        self.assertEqual(body_message["body"], b'{"detail":"Unsupported authentication headers"}')
        self.assertNotIn(b"set-cookie", header_map)

    async def test_get_current_user_returns_session_metadata_from_access_token(self):
        fake_redis = self.FakeRedis()
        token = auth_module.create_access_token(
            {
                "sub": "alice",
                "display_name": "Alice",
                "email": "alice@example.local",
                "groups": ["domain_users"],
                "model": "demo",
                "model_description": "Demo",
                "model_key": "demo",
                "auth_source": "password",
                "auth_time": 1700000000,
                "directory_checked_at": 1700000000,
                "identity_version": 1,
                "type": "access",
            }
        )
        request = types.SimpleNamespace(
            cookies={"access_token": f"Bearer {token}"},
            app=types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=types.SimpleNamespace(redis=fake_redis))),
        )

        current_user = await auth_module.get_current_user(request, credentials=None)

        self.assertEqual(current_user["username"], "alice")
        self.assertEqual(current_user["auth_source"], "password")
        self.assertEqual(current_user["auth_time"], 1700000000)
        self.assertEqual(current_user["directory_checked_at"], 1700000000)
        self.assertEqual(current_user["identity_version"], 1)
        self.assertEqual(
            current_user["canonical_principal"],
            f"alice@{auth_module.settings.KERBEROS_REALM.upper()}",
        )

    def test_build_identity_contract_normalizes_domain_and_upn_inputs(self):
        by_domain = auth_module.build_identity_contract("DOMAIN\\Alice")
        by_upn = auth_module.build_identity_contract("ALICE@YOUR-DOMAIN.LOCAL")
        by_username = auth_module.build_identity_contract("alice")

        self.assertEqual(by_domain["username"], "alice")
        self.assertEqual(by_upn["username"], "alice")
        self.assertEqual(by_username["username"], "alice")
        expected_principal = f"alice@{auth_module.settings.KERBEROS_REALM.upper()}"
        self.assertEqual(by_domain["canonical_principal"], expected_principal)
        self.assertEqual(by_upn["canonical_principal"], expected_principal)
        self.assertEqual(by_username["canonical_principal"], expected_principal)

    async def test_refresh_rotates_refresh_token_and_revokes_previous_one(self):
        fake_redis = self.FakeRedis()
        current_user = {
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.local",
            "groups": ["domain_users"],
            "model": "demo",
            "model_description": "Demo",
            "model_key": "demo",
            "auth_source": "password",
            "auth_time": 1700000000,
            "directory_checked_at": 1700000000,
            "identity_version": 1,
        }
        refresh_token = auth_module.create_access_token(app_module.build_token_payload(current_user, "refresh"))
        refresh_payload = auth_module.jwt.decode(
            refresh_token,
            auth_module.settings.SECRET_KEY,
            algorithms=[auth_module.settings.ALGORITHM],
        )
        request = self.make_request(
            headers={
                "host": "assistant.local",
                "origin": "https://assistant.local",
                "X-CSRF-Token": "csrf-token",
            },
            cookies={
                "refresh_token": f"Bearer {refresh_token}",
                "csrf_token": "csrf-token",
            },
        )
        request.app = types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=types.SimpleNamespace(redis=fake_redis)))

        response = await app_module.refresh_access_token(request)

        self.assertEqual(response.status_code, 204)
        new_access_cookie = self.extract_cookie_value(response, "access_token")
        new_refresh_cookie = self.extract_cookie_value(response, "refresh_token")
        self.assertIsNotNone(new_access_cookie)
        self.assertIsNotNone(new_refresh_cookie)
        self.assertNotEqual(new_refresh_cookie, f"Bearer {refresh_token}")
        self.assertIn(auth_module.token_revocation_key(refresh_payload["jti"]), fake_redis.storage)

    async def test_logout_revokes_tokens_and_clears_cookies(self):
        fake_redis = self.FakeRedis()
        access_token = auth_module.create_access_token(
            {
                "sub": "alice",
                "display_name": "Alice",
                "email": "alice@example.local",
                "groups": ["domain_users"],
                "model": "demo",
                "model_description": "Demo",
                "model_key": "demo",
                "type": "access",
            }
        )
        refresh_token = auth_module.create_access_token(
            {
                "sub": "alice",
                "display_name": "Alice",
                "email": "alice@example.local",
                "groups": ["domain_users"],
                "model": "demo",
                "model_description": "Demo",
                "model_key": "demo",
                "type": "refresh",
            }
        )
        request = self.make_request(
            headers={
                "host": "assistant.local",
                "origin": "https://assistant.local",
                "X-CSRF-Token": "csrf-token",
            },
            cookies={
                "access_token": f"Bearer {access_token}",
                "refresh_token": f"Bearer {refresh_token}",
                "csrf_token": "csrf-token",
            },
        )
        request.app = types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=types.SimpleNamespace(redis=fake_redis)))
        current_user = {"username": "alice"}

        response = await app_module.logout(request, current_user=current_user)

        self.assertEqual(response.status_code, 200)
        self.assertIn("redirect", response.body.decode("utf-8", errors="ignore"))
        deleted_cookie_headers = [value.decode("utf-8", errors="ignore") for header, value in response.raw_headers if header.lower() == b"set-cookie"]
        self.assertTrue(any(header.startswith("access_token=") for header in deleted_cookie_headers))
        self.assertTrue(any(header.startswith("refresh_token=") for header in deleted_cookie_headers))

    def test_model_authorization_hides_models_without_explicit_policy(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding"},
            "orphan-model:latest": {"name": "orphan-model:latest", "description": "Unknown"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)):
                allowed = auth_module.get_allowed_models_for_user({"groups": ["domain_users"]}, models)

        self.assertEqual(list(allowed.keys()), ["phi3:mini"])
        self.assertNotIn("orphan-model:latest", allowed)

    def test_model_authorization_allows_additional_categories_only_from_explicit_policy(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding"},
            "llama3.1:8b": {"name": "llama3.1:8b", "description": "Admin"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)), patch.object(
                auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"
            ), patch.object(auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"):
                developer_allowed = auth_module.get_allowed_models_for_user({"groups": ["ai-developers"]}, models)
                admin_allowed = auth_module.get_allowed_models_for_user({"groups": ["ai-admins"]}, models)
                combined_allowed = auth_module.get_allowed_models_for_user(
                    {"groups": ["ai-developers", "ai-admins"]},
                    models,
                )

        self.assertEqual(list(developer_allowed.keys()), ["phi3:mini", "codellama:13b"])
        self.assertEqual(list(admin_allowed.keys()), ["phi3:mini", "llama3.1:8b"])
        self.assertEqual(list(combined_allowed.keys()), ["phi3:mini", "codellama:13b", "llama3.1:8b"])

    def test_model_authorization_allows_all_policy_categories_for_configured_validation_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding"},
            "llama3.1:8b": {"name": "llama3.1:8b", "description": "Admin"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)), patch.object(
                auth_module.settings, "INSTALL_TEST_USER", "aitest"
            ), patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", ""), patch.object(
                auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", ""
            ):
                validation_allowed = auth_module.get_allowed_models_for_user(
                    {"username": "aitest", "groups": ["domain_users"]},
                    models,
                )
                normal_allowed = auth_module.get_allowed_models_for_user(
                    {"username": "alice", "groups": ["domain_users"]},
                    models,
                )

        self.assertEqual(list(validation_allowed.keys()), ["phi3:mini", "codellama:13b", "llama3.1:8b"])
        self.assertEqual(list(normal_allowed.keys()), ["phi3:mini"])

    def test_model_authorization_fails_closed_when_policy_catalog_is_missing(self):
        models = {"phi3:mini": {"name": "phi3:mini", "description": "General"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            missing_root = Path(temp_dir) / "missing"
            with patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(missing_root)):
                allowed = auth_module.get_allowed_models_for_user({"groups": ["domain_users"]}, models)

        self.assertEqual(allowed, {})

    def test_model_authorization_fails_closed_when_policy_catalog_is_empty(self):
        models = {"phi3:mini": {"name": "phi3:mini", "description": "General"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            empty_root = Path(temp_dir)
            with patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(empty_root)):
                allowed = auth_module.get_allowed_models_for_user({"groups": ["domain_users"]}, models)

        self.assertEqual(allowed, {})

    async def test_api_models_returns_only_policy_allowed_models_for_general_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General", "size": "1", "status": "active"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding", "size": "2", "status": "active"},
            "orphan-model:latest": {"name": "orphan-model:latest", "description": "Unknown", "size": "3", "status": "active"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway)))
        current_user = {"username": "alice", "groups": ["domain_users"]}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module.settings, "get_available_models", return_value=models), patch.object(
                auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)
            ), patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"), patch.object(
                auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"
            ):
                response = await app_module.get_available_models(request, current_user=current_user)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["key"] for item in payload], ["phi3:mini"])

    async def test_api_models_returns_category_filtered_models_for_sso_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General", "size": "1", "status": "active"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding", "size": "2", "status": "active"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway)))
        current_user = {"username": "aitest", "groups": ["AI_Users"], "auth_source": "sso"}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module.settings, "get_available_models", return_value=models), patch.object(
                auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)
            ), patch.object(auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai_users"), patch.object(
                auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai_admins"
            ):
                response = await app_module.get_available_models(request, current_user=current_user)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["key"] for item in payload], ["phi3:mini", "codellama:13b"])

    async def test_api_models_returns_all_baseline_policy_models_for_configured_validation_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General", "size": "1", "status": "active"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding", "size": "2", "status": "active"},
            "llama3.1:8b": {"name": "llama3.1:8b", "description": "Admin", "size": "3", "status": "active"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway)))
        current_user = {"username": "aitest", "groups": ["domain_users"], "auth_source": "password"}

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module.settings, "get_available_models", return_value=models), patch.object(
                auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)
            ), patch.object(auth_module.settings, "INSTALL_TEST_USER", "aitest"), patch.object(
                auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", ""
            ), patch.object(auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", ""):
                response = await app_module.get_available_models(request, current_user=current_user)

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["key"] for item in payload], ["phi3:mini", "codellama:13b", "llama3.1:8b"])

    async def test_switch_model_rejects_disallowed_model_for_general_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway)))
        current_user = {
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.local",
            "groups": ["domain_users"],
            "model": "phi3:mini",
            "model_description": "General",
            "model_key": "phi3:mini",
            "auth_source": "password",
            "auth_time": 1700000000,
            "directory_checked_at": 1700000000,
            "identity_version": 1,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
                app_module.settings,
                "get_available_models",
                return_value=models,
            ), patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)), patch.object(
                auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"
            ), patch.object(auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"):
                response = await app_module.switch_user_model(
                    request,
                    payload=app_module.ModelSwitchRequest(model="codellama:13b"),
                    current_user=current_user,
                )

        self.assertEqual(response.status_code, 403)

    async def test_switch_model_allows_policy_permitted_model_for_developer_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "codellama:13b": {"name": "codellama:13b", "description": "Coding"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = self.make_request()
        request.app = types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway))
        current_user = {
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.local",
            "groups": ["ai-developers"],
            "model": "phi3:mini",
            "model_description": "General",
            "model_key": "phi3:mini",
            "auth_source": "password",
            "auth_time": 1700000000,
            "directory_checked_at": 1700000000,
            "identity_version": 1,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
                app_module.settings,
                "get_available_models",
                return_value=models,
            ), patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)), patch.object(
                auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai-developers"
            ), patch.object(auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai-admins"):
                response = await app_module.switch_user_model(
                    request,
                    payload=app_module.ModelSwitchRequest(model="codellama:13b"),
                    current_user=current_user,
                )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertEqual(payload["key"], "codellama:13b")

    async def test_switch_model_rejects_disallowed_model_for_sso_user(self):
        models = {
            "phi3:mini": {"name": "phi3:mini", "description": "General"},
            "llama3.1:8b": {"name": "llama3.1:8b", "description": "Admin"},
        }
        gateway = types.SimpleNamespace(set_model_catalog=AsyncMock(return_value=None))
        request = self.make_request()
        request.app = types.SimpleNamespace(state=types.SimpleNamespace(llm_gateway=gateway))
        current_user = {
            "username": "aitest",
            "display_name": "AI Test",
            "email": "aitest@example.local",
            "groups": ["AI_Users"],
            "model": "phi3:mini",
            "model_description": "General",
            "model_key": "phi3:mini",
            "auth_source": "sso",
            "auth_time": 1700000000,
            "directory_checked_at": 1700000000,
            "identity_version": 1,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            policy_root = Path(temp_dir)
            self.write_policy_catalog(policy_root)
            with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
                app_module.settings,
                "get_available_models",
                return_value=models,
            ), patch.object(auth_module.settings, "MODEL_POLICY_DIR", str(policy_root)), patch.object(
                auth_module.settings, "MODEL_ACCESS_CODING_GROUPS", "ai_users"
            ), patch.object(auth_module.settings, "MODEL_ACCESS_ADMIN_GROUPS", "ai_admins"):
                response = await app_module.switch_user_model(
                    request,
                    payload=app_module.ModelSwitchRequest(model="llama3.1:8b"),
                    current_user=current_user,
                )

        self.assertEqual(response.status_code, 403)

    async def test_sso_proxy_validate_returns_403_when_sso_is_disabled(self):
        with patch.object(sso_proxy_module.settings, "SSO_ENABLED", False), patch.object(
            sso_proxy_module.settings,
            "TRUSTED_AUTH_PROXY_ENABLED",
            False,
        ):
            helper_app = sso_proxy_module.create_app()
            validate = self.get_route_endpoint(helper_app, "/validate")
            response = await validate(self.make_request(path="/validate"))

        self.assertEqual(response.status_code, 403)

    async def test_sso_proxy_validate_requests_negotiate_when_authorization_header_missing(self):
        with patch.object(sso_proxy_module.settings, "SSO_ENABLED", True), patch.object(
            sso_proxy_module.settings,
            "TRUSTED_AUTH_PROXY_ENABLED",
            True,
        ), patch.object(sso_proxy_module.settings, "SSO_SERVICE_PRINCIPAL", "HTTP/assistant.example.local@EXAMPLE.LOCAL"), patch.object(
            sso_proxy_module.settings,
            "SSO_KEYTAB_PATH",
            "/tmp/http.keytab",
        ), patch.object(
            sso_proxy_module,
            "gssapi",
            object(),
        ), patch("sso_proxy_auth.os.path.exists", return_value=True):
            helper_app = sso_proxy_module.create_app()
            validate = self.get_route_endpoint(helper_app, "/validate")
            response = await validate(self.make_request(path="/validate"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("www-authenticate"), "Negotiate")

    async def test_sso_proxy_validate_returns_identity_headers_on_success(self):
        identity = {
            "username": "aitest",
            "canonical_principal": "aitest@EXAMPLE.LOCAL",
            "display_name": "AI Test",
            "email": "aitest@example.local",
            "groups": ["AI_Users"],
            "auth_source": "sso",
        }

        with patch.object(sso_proxy_module.settings, "SSO_ENABLED", True), patch.object(
            sso_proxy_module.settings,
            "TRUSTED_AUTH_PROXY_ENABLED",
            True,
        ), patch.object(sso_proxy_module.settings, "SSO_SERVICE_PRINCIPAL", "HTTP/assistant.example.local@EXAMPLE.LOCAL"), patch.object(
            sso_proxy_module.settings,
            "SSO_KEYTAB_PATH",
            "/tmp/http.keytab",
        ), patch.object(
            sso_proxy_module,
            "gssapi",
            object(),
        ), patch("sso_proxy_auth.os.path.exists", return_value=True), patch.object(
            sso_proxy_module,
            "authenticate_negotiate_token",
            return_value=("aitest@EXAMPLE.LOCAL", None),
        ), patch.object(
            sso_proxy_module,
            "_resolve_sso_identity",
            return_value=identity,
        ):
            helper_app = sso_proxy_module.create_app()
            validate = self.get_route_endpoint(helper_app, "/validate")
            response = await validate(
                self.make_request(
                    path="/validate",
                    headers={"authorization": "Negotiate opaque"},
                )
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("x-authenticated-user"), "aitest")
        self.assertEqual(response.headers.get("x-authenticated-principal"), "aitest@EXAMPLE.LOCAL")
        self.assertEqual(response.headers.get("x-authenticated-email"), "aitest@example.local")
        self.assertEqual(response.headers.get("x-authenticated-groups"), '["AI_Users"]')


if __name__ == "__main__":
    unittest.main()

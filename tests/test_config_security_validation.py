import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import config as config_module
from local_admin_security import build_local_admin_password_hash


class ConfigSecurityValidationTests(unittest.TestCase):
    def test_default_settings_keep_enterprise_ad_contract(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
        )

        self.assertEqual(settings.INSTALL_PROFILE, "enterprise")
        self.assertEqual(settings.AUTH_MODE, "ad")
        self.assertFalse(settings.STANDALONE_CHAT_AUTH_ENABLED)
        self.assertEqual(settings.STANDALONE_CHAT_USERNAME, "demo_ai")
        self.assertEqual(settings.STANDALONE_CHAT_PASSWORD_HASH, "")
        self.assertFalse(settings.LAB_OPEN_AUTH_ACK)

    def test_unknown_install_profile_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                INSTALL_PROFILE="unknown-profile",
            )

        self.assertIn("INSTALL_PROFILE must be one of", str(error.exception))

    def test_unknown_auth_mode_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                AUTH_MODE="open",
            )

        self.assertIn("AUTH_MODE must be one of", str(error.exception))

    def test_lab_open_requires_explicit_ack(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                INSTALL_PROFILE="standalone_gpu_lab",
                AUTH_MODE="lab_open",
                LAB_OPEN_AUTH_ACK=False,
            )

        self.assertIn("AUTH_MODE=lab_open requires LAB_OPEN_AUTH_ACK=true", str(error.exception))

    def test_enterprise_profile_rejects_non_ad_auth_mode(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                INSTALL_PROFILE="enterprise",
                AUTH_MODE="lab_open",
                LAB_OPEN_AUTH_ACK=True,
            )

        self.assertIn("INSTALL_PROFILE=enterprise requires AUTH_MODE=ad", str(error.exception))

    def test_standalone_gpu_lab_profile_accepts_ad_contract(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            INSTALL_PROFILE="standalone_gpu_lab",
            AUTH_MODE="ad",
        )

        self.assertEqual(settings.INSTALL_PROFILE, "standalone_gpu_lab")
        self.assertEqual(settings.AUTH_MODE, "ad")
        self.assertFalse(settings.lab_open_auth_enabled)

    def test_standalone_chat_auth_requires_hash_when_enabled(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                AUTH_MODE="ad",
                STANDALONE_CHAT_AUTH_ENABLED=True,
                STANDALONE_CHAT_USERNAME="demo_ai",
                STANDALONE_CHAT_PASSWORD_HASH="",
            )

        self.assertIn("STANDALONE_CHAT_PASSWORD_HASH must be set when standalone chat auth is enabled", str(error.exception))

    def test_standalone_chat_hash_only_contract_is_valid(self):
        password_hash = build_local_admin_password_hash("StandaloneTestPassword-123")

        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            AUTH_MODE="ad",
            STANDALONE_CHAT_AUTH_ENABLED=True,
            STANDALONE_CHAT_USERNAME="Demo_AI",
            STANDALONE_CHAT_PASSWORD_HASH=password_hash,
            INSTALL_TEST_USER="Demo_AI",
        )

        self.assertTrue(settings.STANDALONE_CHAT_AUTH_ENABLED)
        self.assertEqual(settings.STANDALONE_CHAT_USERNAME, "demo_ai")
        self.assertEqual(settings.STANDALONE_CHAT_PASSWORD_HASH, password_hash)
        self.assertEqual(settings.INSTALL_TEST_USER, "demo_ai")
        self.assertFalse(settings.lab_open_auth_enabled)

    def test_legacy_lab_open_contract_remains_valid_when_acknowledged(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            INSTALL_PROFILE="standalone_gpu_lab",
            AUTH_MODE="lab_open",
            LAB_OPEN_AUTH_ACK=True,
            LAB_USER_USERNAME="lab_user",
            LAB_USER_CANONICAL_PRINCIPAL="lab_user@LOCAL.LAB",
        )

        self.assertEqual(settings.INSTALL_PROFILE, "standalone_gpu_lab")
        self.assertEqual(settings.AUTH_MODE, "lab_open")
        self.assertTrue(settings.lab_open_auth_enabled)

    def test_remote_redis_password_placeholder_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                REDIS_URL="redis://:redis-secret-123@redis:6379/0",
                REDIS_PASSWORD="change-me",
            )

        self.assertIn("Password uses an insecure placeholder value", str(error.exception))

    def test_remote_redis_url_placeholder_is_rejected(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                REDIS_URL="redis://:change-me@redis:6379/0",
                REDIS_PASSWORD="redis-secret-123",
            )

        self.assertIn("REDIS_URL embeds an insecure placeholder password", str(error.exception))

    def test_remote_redis_requires_explicit_password_for_non_local_service(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                REDIS_URL="redis://redis:6379/0",
                REDIS_PASSWORD="",
            )

        self.assertIn("REDIS_PASSWORD must be set for non-local Redis deployments", str(error.exception))

    def test_postgres_password_placeholder_is_rejected_for_enabled_persistence(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL="postgresql+psycopg://corporate_ai:postgres-secret-123@postgres:5432/corporate_ai",
                POSTGRES_PASSWORD="change-me",
            )

        self.assertIn("Password uses an insecure placeholder value", str(error.exception))

    def test_postgres_url_placeholder_is_rejected_for_enabled_persistence(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL="postgresql+psycopg://corporate_ai:change-me@postgres:5432/corporate_ai",
                POSTGRES_PASSWORD="postgres-secret-123",
            )

        self.assertIn("PERSISTENT_DB_URL embeds an insecure placeholder password", str(error.exception))

    def test_enabled_remote_postgres_requires_password_when_url_is_configured(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                PERSISTENT_DB_ENABLED=True,
                PERSISTENT_DB_URL="postgresql+psycopg://corporate_ai@postgres:5432/corporate_ai",
                POSTGRES_PASSWORD="",
            )

        self.assertIn("POSTGRES_PASSWORD must be set for non-local PostgreSQL deployments", str(error.exception))

    def test_trusted_proxy_sso_requires_explicit_cidrs(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                SSO_ENABLED=True,
                TRUSTED_AUTH_PROXY_ENABLED=True,
                TRUSTED_PROXY_SOURCE_CIDRS="",
            )

        self.assertIn("TRUSTED_PROXY_SOURCE_CIDRS must be set when trusted proxy SSO is enabled", str(error.exception))

    def test_trusted_proxy_source_cidrs_must_be_valid(self):
        with self.assertRaises(ValidationError) as error:
            config_module.Settings(
                SECRET_KEY="x" * 40,
                COOKIE_SECURE=False,
                TRUSTED_PROXY_SOURCE_CIDRS="not-a-cidr",
            )

        self.assertIn("TRUSTED_PROXY_SOURCE_CIDRS must contain a comma-separated list of valid CIDRs", str(error.exception))

    def test_installer_like_secure_service_secrets_remain_valid(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            REDIS_URL="redis://:redis-secret-123@redis:6379/0",
            REDIS_PASSWORD="redis-secret-123",
            PERSISTENT_DB_ENABLED=True,
            PERSISTENT_DB_URL="postgresql+psycopg://corporate_ai:postgres-secret-123@postgres:5432/corporate_ai",
            POSTGRES_PASSWORD="postgres-secret-123",
            TRUSTED_PROXY_SOURCE_CIDRS="127.0.0.1/32,10.0.0.0/24",
        )

        self.assertEqual(settings.REDIS_PASSWORD, "redis-secret-123")
        self.assertEqual(settings.POSTGRES_PASSWORD, "postgres-secret-123")


if __name__ == "__main__":
    unittest.main()

import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import config as config_module


class ConfigSecurityValidationTests(unittest.TestCase):
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

    def test_installer_like_secure_service_secrets_remain_valid(self):
        settings = config_module.Settings(
            SECRET_KEY="x" * 40,
            COOKIE_SECURE=False,
            REDIS_URL="redis://:redis-secret-123@redis:6379/0",
            REDIS_PASSWORD="redis-secret-123",
            PERSISTENT_DB_ENABLED=True,
            PERSISTENT_DB_URL="postgresql+psycopg://corporate_ai:postgres-secret-123@postgres:5432/corporate_ai",
            POSTGRES_PASSWORD="postgres-secret-123",
        )

        self.assertEqual(settings.REDIS_PASSWORD, "redis-secret-123")
        self.assertEqual(settings.POSTGRES_PASSWORD, "postgres-secret-123")


if __name__ == "__main__":
    unittest.main()

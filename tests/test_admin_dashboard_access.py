import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class AdminDashboardAccessTests(unittest.IsolatedAsyncioTestCase):
    def test_user_is_admin_allows_expected_admin_groups(self):
        self.assertTrue(app_module.user_is_admin({"groups": ["AI-Admins"]}))
        self.assertTrue(app_module.user_is_admin({"groups": ["corp-admins"]}))
        self.assertTrue(app_module.user_is_admin({"groups": ["Domain Admins"]}))

    def test_user_is_admin_rejects_substring_false_positives(self):
        self.assertFalse(app_module.user_is_admin({"groups": ["project-admin-reviewers"]}))
        self.assertFalse(app_module.user_is_admin({"groups": ["readmin-team"]}))
        self.assertFalse(app_module.user_is_admin({"groups": ["admin-console-users"]}))

    def test_parse_admin_dashboard_allowed_users_normalizes_and_ignores_empty_entries(self):
        allowed = app_module.parse_admin_dashboard_allowed_users(" aitest@corp.local , , CORP\\alice,invalid user ")

        self.assertEqual(allowed, frozenset({"aitest", "alice"}))

    async def test_guard_allows_user_from_env_allowlist(self):
        user = {"username": "alice", "display_name": "Alice"}

        with unittest.mock.patch.object(app_module.settings, "ADMIN_DASHBOARD_USERS", "alice"):
            app_module.parse_admin_dashboard_allowed_users.cache_clear()
            result = await app_module.get_admin_dashboard_user_required(user)

        self.assertEqual(result["username"], "alice")

    async def test_guard_normalizes_username_before_allow_check(self):
        user = {"username": "AITEST@CORP.LOCAL"}

        with unittest.mock.patch.object(app_module.settings, "ADMIN_DASHBOARD_USERS", " aitest , "):
            app_module.parse_admin_dashboard_allowed_users.cache_clear()
            result = await app_module.get_admin_dashboard_user_required(user)
            self.assertTrue(app_module.user_can_access_admin_dashboard(user))

        self.assertEqual(result["username"], "AITEST@CORP.LOCAL")

    async def test_empty_allowlist_denies_everyone(self):
        with unittest.mock.patch.object(app_module.settings, "ADMIN_DASHBOARD_USERS", ""):
            app_module.parse_admin_dashboard_allowed_users.cache_clear()
            with self.assertRaises(HTTPException) as error:
                await app_module.get_admin_dashboard_user_required({"username": "alice"})

        self.assertEqual(error.exception.status_code, 403)

    async def test_guard_denies_user_outside_allowlist(self):
        with unittest.mock.patch.object(app_module.settings, "ADMIN_DASHBOARD_USERS", "bob"):
            app_module.parse_admin_dashboard_allowed_users.cache_clear()
            with self.assertRaises(HTTPException) as error:
                await app_module.get_admin_dashboard_user_required({"username": "alice"})

        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

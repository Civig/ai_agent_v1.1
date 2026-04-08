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

    async def test_guard_allows_aitest(self):
        user = {"username": "aitest", "display_name": "AI Test"}

        result = await app_module.get_admin_dashboard_user_required(user)

        self.assertEqual(result["username"], "aitest")

    async def test_guard_normalizes_username_before_allow_check(self):
        user = {"username": "AITEST@CORP.LOCAL"}

        result = await app_module.get_admin_dashboard_user_required(user)

        self.assertEqual(result["username"], "AITEST@CORP.LOCAL")
        self.assertTrue(app_module.user_can_access_admin_dashboard(user))

    async def test_guard_denies_non_aitest_user(self):
        with self.assertRaises(HTTPException) as error:
            await app_module.get_admin_dashboard_user_required({"username": "alice"})

        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

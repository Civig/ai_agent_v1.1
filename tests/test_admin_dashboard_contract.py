import unittest
from pathlib import Path


class AdminDashboardContractTests(unittest.TestCase):
    def test_runtime_and_docs_use_admin_dashboard_users_contract(self):
        app_text = Path("app.py").read_text(encoding="utf-8-sig")
        config_text = Path("config.py").read_text(encoding="utf-8-sig")
        env_text = Path(".env.example").read_text(encoding="utf-8")
        install_text = Path("install.sh").read_text(encoding="utf-8")
        install_ru_text = Path("docs/INSTALL_ru.md").read_text(encoding="utf-8")
        security_ru_text = Path("docs/SECURITY_ru.md").read_text(encoding="utf-8")

        self.assertNotIn('frozenset({"aitest"})', app_text)
        self.assertIn("ADMIN_DASHBOARD_USERS", app_text)
        self.assertIn("ADMIN_DASHBOARD_USERS", config_text)
        self.assertIn("ADMIN_DASHBOARD_USERS=", env_text)
        self.assertIn("ADMIN_DASHBOARD_USERS", install_text)
        self.assertIn("ADMIN_DASHBOARD_USERS", install_ru_text)
        self.assertIn("ADMIN_DASHBOARD_USERS", security_ru_text)


if __name__ == "__main__":
    unittest.main()

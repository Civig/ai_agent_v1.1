import io
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("redis", types.SimpleNamespace(Redis=object))

import runtime_healthcheck


class RuntimeHealthcheckContractTests(unittest.TestCase):
    def test_check_app_accepts_start_app_pid1_and_checks_http(self):
        with patch("builtins.open", return_value=io.BytesIO(b"python\x00start_app.py\x00")):
            with patch("runtime_healthcheck.check_http") as check_http:
                runtime_healthcheck.check_app()

        check_http.assert_called_once_with("http://127.0.0.1:8000/health/live")

    def test_check_app_rejects_unrelated_pid1(self):
        with patch("builtins.open", return_value=io.BytesIO(b"python\x00worker.py\x00")):
            with patch("runtime_healthcheck.check_http"):
                with self.assertRaisesRegex(RuntimeError, "pid1 does not look like start_app.py"):
                    runtime_healthcheck.check_app()

    def test_main_app_mode_uses_check_app_contract(self):
        with patch("runtime_healthcheck.check_app") as check_app:
            with patch("sys.argv", ["runtime_healthcheck.py", "app"]):
                status = runtime_healthcheck.main()

        self.assertEqual(status, 0)
        check_app.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

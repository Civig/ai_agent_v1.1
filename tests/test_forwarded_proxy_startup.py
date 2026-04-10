import socket
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import start_app


class ForwardedProxyStartupTests(unittest.TestCase):
    def test_resolve_forwarded_allow_ips_honors_env_override(self):
        value = start_app.resolve_forwarded_allow_ips({"FORWARDED_ALLOW_IPS": "10.10.0.0/24,127.0.0.1"})
        self.assertEqual(value, "10.10.0.0/24,127.0.0.1")

    def test_build_default_forwarded_allow_ips_uses_local_interface_networks_and_loopback(self):
        fake_interfaces = {
            "lo": [
                SimpleNamespace(family=socket.AF_INET, address="127.0.0.1", netmask="255.0.0.0"),
                SimpleNamespace(family=socket.AF_INET6, address="::1", netmask="ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"),
            ],
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="172.22.0.5", netmask="255.255.0.0"),
            ],
        }
        with patch("start_app.get_interface_addresses", return_value=fake_interfaces):
            value = start_app.build_default_forwarded_allow_ips()

        allowlist = value.split(",")
        self.assertIn("127.0.0.1", allowlist)
        self.assertIn("::1", allowlist)
        self.assertIn("172.22.0.0/16", allowlist)
        self.assertNotIn("*", allowlist)

    def test_build_uvicorn_run_kwargs_never_uses_wildcard(self):
        fake_interfaces = {
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="172.30.1.9", netmask="255.255.0.0"),
            ],
        }
        with patch("start_app.get_interface_addresses", return_value=fake_interfaces):
            kwargs = start_app.build_uvicorn_run_kwargs({})

        self.assertTrue(kwargs["proxy_headers"])
        self.assertEqual(kwargs["app"], "app:app")
        self.assertNotEqual(kwargs["forwarded_allow_ips"], "*")
        self.assertIn("172.30.0.0/16", str(kwargs["forwarded_allow_ips"]))

    def test_repo_runtime_contract_uses_startup_helper_and_not_wildcard(self):
        dockerfile_text = Path("Dockerfile").read_text(encoding="utf-8-sig")
        self.assertIn('CMD ["python", "start_app.py"]', dockerfile_text)
        self.assertNotIn("--forwarded-allow-ips=*", dockerfile_text)

    def test_env_example_installer_and_docs_expose_forwarded_allow_ips(self):
        env_example_text = Path(".env.example").read_text(encoding="utf-8")
        install_script_text = Path("install.sh").read_text(encoding="utf-8")
        install_ru_text = Path("docs/INSTALL_ru.md").read_text(encoding="utf-8")
        security_ru_text = Path("docs/SECURITY_ru.md").read_text(encoding="utf-8")

        self.assertIn("FORWARDED_ALLOW_IPS=", env_example_text)
        self.assertIn("FORWARDED_ALLOW_IPS", install_script_text)
        self.assertIn("FORWARDED_ALLOW_IPS", install_ru_text)
        self.assertIn("FORWARDED_ALLOW_IPS", security_ru_text)


if __name__ == "__main__":
    unittest.main()

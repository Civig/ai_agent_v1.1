import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import auth_kerberos as auth_module


class AuthGssapiServiceHostTests(unittest.TestCase):
    def _make_auth(self, *, ldap_server: str, gssapi_host: str):
        patches = (
            patch.object(auth_module.settings, "LDAP_SERVER", ldap_server),
            patch.object(auth_module.settings, "LDAP_GSSAPI_SERVICE_HOST", gssapi_host),
            patch.object(auth_module.settings, "LDAP_BASE_DN", "DC=corp,DC=local"),
            patch.object(auth_module.settings, "LDAP_DOMAIN", "corp.local"),
            patch.object(auth_module.settings, "KERBEROS_REALM", "CORP.LOCAL"),
            patch.object(auth_module.settings, "KERBEROS_KDC", "srv-ad.corp.local"),
        )
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return auth_module.KerberosAuth()

    def test_explicit_gssapi_service_host_rewrites_only_ldapsearch_host(self):
        auth = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local:389",
            gssapi_host="srv-ad",
        )

        command = auth._build_ldapsearch_command("alice")

        self.assertEqual(auth.ldap_server, "ldap://srv-ad.corp.local:389")
        self.assertEqual(command[6], "ldap://srv-ad:389")

    def test_ldapsearch_falls_back_to_original_uri_when_override_is_missing(self):
        auth = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local",
            gssapi_host="",
        )

        command = auth._build_ldapsearch_command("alice")

        self.assertEqual(command[6], "ldap://srv-ad.corp.local")

    def test_build_env_enables_sasl_nocanon_only_when_override_is_explicit(self):
        auth = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local",
            gssapi_host="srv-ad",
        )

        env = auth._build_env("/tmp/krb5cc_test", "/tmp/krb5_test.conf")

        self.assertEqual(env["SASL_NOCANON"], "on")

        auth_without_override = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local",
            gssapi_host="",
        )
        env_without_override = auth_without_override._build_env("/tmp/krb5cc_test", "/tmp/krb5_test.conf")

        self.assertNotIn("SASL_NOCANON", env_without_override)

    def test_ldapsearch_command_preserves_base_dn_and_filter(self):
        auth = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local",
            gssapi_host="srv-ad",
        )

        command = auth._build_ldapsearch_command("alice@example")

        self.assertIn("-b", command)
        self.assertIn("DC=corp,DC=local", command)
        self.assertIn("(sAMAccountName=alice@example)", command)

    def test_explicit_gssapi_service_host_builds_fully_no_canon_krb5_config(self):
        auth = self._make_auth(
            ldap_server="ldap://srv-ad.corp.local",
            gssapi_host="srv-ad",
        )

        krb5_path = auth._create_krb5_config()
        self.addCleanup(lambda: Path(krb5_path).unlink(missing_ok=True))

        config_text = Path(krb5_path).read_text(encoding="utf-8")

        self.assertIn("dns_canonicalize_hostname = false", config_text)
        self.assertIn("rdns = false", config_text)
        self.assertIn('qualify_shortname = ""', config_text)


if __name__ == "__main__":
    unittest.main()

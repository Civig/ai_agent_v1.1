import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.model_contract_test_helper import exported_canonical_default_model


class InstallPostgresProfileTests(unittest.TestCase):
    def _copy_install_fixture(self, temp_dir: str) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "install.sh",
            ".env.example",
            "docker-compose.yml",
            "models/catalog.json",
            "tools/export_installer_model_catalog.py",
        ):
            source_path = repo_root / relative_path
            target_path = Path(temp_dir) / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        return Path(temp_dir)

    def _run_write_env_file(self, temp_dir: str, *, existing_env: str | None = None) -> str:
        temp_root = self._copy_install_fixture(temp_dir)
        env_file = temp_root / ".env"
        if existing_env is not None:
            env_file.write_text(existing_env, encoding="utf-8")

        shell_script = textwrap.dedent(
            """
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            DOMAIN="corp.local"
            LDAP_SERVER_URL="ldap://srv-ad.corp.local"
            if [[ -f ".env" ]]; then
                LDAP_GSSAPI_SERVICE_HOST="$(get_env_value ".env" "LDAP_GSSAPI_SERVICE_HOST" || true)"
            else
                LDAP_GSSAPI_SERVICE_HOST="srv-ad"
            fi
            BASE_DN="DC=corp,DC=local"
            NETBIOS_DOMAIN="CORP"
            KERBEROS_REALM="CORP.LOCAL"
            KERBEROS_KDC="srv-ad.corp.local"
            SECRET_KEY="test-secret-key-1234567890-test-abcdef"
            SSO_ENABLED="false"
            SSO_SERVICE_PRINCIPAL=""
            SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
            MODEL_ACCESS_CODING_GROUPS=""
            MODEL_ACCESS_ADMIN_GROUPS=""
            DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
            REDIS_PASSWORD="redis-secret"
            POSTGRES_DB="corporate_ai"
            POSTGRES_USER="corporate_ai"
            POSTGRES_PASSWORD="postgres-secret"
            SELECTED_INSTALL_MODE="cpu"
            AD_SERVER_IP_OVERRIDE=""
            TEST_ADMIN_USER=""
            write_env_file
            """
        )
        subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        return env_file.read_text(encoding="utf-8")

    def _run_write_krb5_conf(self, temp_dir: str, *, ldap_gssapi_service_host: str) -> str:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            """
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            DOMAIN="corp.local"
            LDAP_GSSAPI_SERVICE_HOST="$2"
            KERBEROS_REALM="CORP.LOCAL"
            KERBEROS_KDC="srv-ad.corp.local"
            write_krb5_conf
            """
        )
        subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root), ldap_gssapi_service_host],
            check=True,
            capture_output=True,
            text=True,
        )
        return (temp_root / "deploy" / "krb5.conf").read_text(encoding="utf-8")

    def _run_validate_smoke_test_model_contract(
        self,
        temp_dir: str,
        *,
        default_model: str,
        test_admin_user: str,
    ) -> subprocess.CompletedProcess[str]:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            """
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            DEFAULT_MODEL="$2"
            TEST_ADMIN_USER="$3"
            validate_smoke_test_model_contract
            """
        )
        return subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root), default_model, test_admin_user],
            check=False,
            capture_output=True,
            text=True,
        )

    def _run_model_catalog_records(self, temp_dir: str) -> str:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            """
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            model_catalog_records
            """
        )
        result = subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def _run_hot_model_catalog_records(self, temp_dir: str) -> str:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            """
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            hot_model_catalog_records
            """
        )
        result = subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def _run_exported_default_model(self, temp_dir: str) -> str:
        temp_root = self._copy_install_fixture(temp_dir)
        return exported_canonical_default_model(temp_root)

    @staticmethod
    def _parse_model_catalog_keys(records_text: str) -> list[str]:
        keys: list[str] = []
        for line in records_text.splitlines():
            line = line.strip()
            if not line:
                continue
            keys.append(line.split("|", 1)[0])
        return keys

    @staticmethod
    def _parse_hot_model_catalog_keys(records_text: str) -> list[str]:
        keys: list[str] = []
        for line in records_text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            keys.append(parts[1])
        return keys

    @staticmethod
    def _get_env_value(env_text: str, key: str) -> str | None:
        prefix = f"{key}="
        for line in env_text.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def test_fresh_install_profile_enables_postgres_conversation_runtime(self):
        expected_default_model = exported_canonical_default_model(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temp_dir:
            env_text = self._run_write_env_file(temp_dir)

        self.assertEqual(self._get_env_value(env_text, "LDAP_GSSAPI_SERVICE_HOST"), "srv-ad")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_DB"), "corporate_ai")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_USER"), "corporate_ai")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_PASSWORD"), "postgres-secret")
        self.assertEqual(self._get_env_value(env_text, "ADMIN_DASHBOARD_USERS"), "")
        self.assertEqual(self._get_env_value(env_text, "TRUSTED_PROXY_SOURCE_CIDRS"), "127.0.0.1/32,::1/128")
        self.assertEqual(self._get_env_value(env_text, "OLLAMA_PULL_TIMEOUT_SECONDS"), "900")
        self.assertEqual(
            self._get_env_value(env_text, "REDIS_IMAGE"),
            "redis@sha256:8b81dd37ff027bec4e516d41acfbe9fe2460070dc6d4a4570a2ac5b9d59df065",
        )
        self.assertEqual(
            self._get_env_value(env_text, "POSTGRES_IMAGE"),
            "postgres@sha256:2586e2a95d1c9b31cb2967feb562948f7d364854453d703039b6efa45fe48417",
        )
        self.assertEqual(
            self._get_env_value(env_text, "OLLAMA_IMAGE"),
            "ollama/ollama@sha256:5a5d014aa774f78ebe1340c0d4afc2e35afc12a2c3b34c84e71f78ea20af4ba3",
        )
        self.assertEqual(
            self._get_env_value(env_text, "NGINX_IMAGE"),
            "nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10",
        )
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_ENABLED"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_BOOTSTRAP_SCHEMA"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_DUAL_WRITE_CONVERSATION"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_THREADS"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_MESSAGES"), "true")
        self.assertEqual(self._get_env_value(env_text, "DEFAULT_MODEL"), expected_default_model)
        self.assertEqual(
            self._get_env_value(env_text, "PERSISTENT_DB_URL"),
            "postgresql+psycopg://corporate_ai:postgres-secret@postgres:5432/corporate_ai",
        )

    def test_existing_env_preserves_previous_persistence_flags(self):
        existing_env = textwrap.dedent(
            """
            REDIS_PASSWORD=old-redis
            POSTGRES_DB=legacy_db
            POSTGRES_USER=legacy_user
            POSTGRES_PASSWORD=legacy_pw
            TRUSTED_PROXY_SOURCE_CIDRS=10.0.0.0/24
            OLLAMA_PULL_TIMEOUT_SECONDS=1800
            REDIS_IMAGE=redis@sha256:legacy
            POSTGRES_IMAGE=postgres@sha256:legacy
            OLLAMA_IMAGE=ollama/ollama@sha256:legacy
            NGINX_IMAGE=nginx@sha256:legacy
            PERSISTENT_DB_ENABLED=false
            PERSISTENT_DB_URL=postgresql+psycopg://legacy_user:legacy_pw@postgres:5432/legacy_db
            PERSISTENT_DB_BOOTSTRAP_SCHEMA=false
            PERSISTENT_DB_SHADOW_COMPARE=true
            PERSISTENT_DB_READ_THREADS=false
            PERSISTENT_DB_READ_MESSAGES=false
            PERSISTENT_DB_DUAL_WRITE_CONVERSATION=false
            LDAP_GSSAPI_SERVICE_HOST=legacy-ldap
            """
        ).strip()
        with tempfile.TemporaryDirectory() as temp_dir:
            env_text = self._run_write_env_file(temp_dir, existing_env=existing_env)

        self.assertEqual(self._get_env_value(env_text, "LDAP_GSSAPI_SERVICE_HOST"), "legacy-ldap")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_DB"), "legacy_db")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_USER"), "legacy_user")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_PASSWORD"), "legacy_pw")
        self.assertEqual(self._get_env_value(env_text, "ADMIN_DASHBOARD_USERS"), "")
        self.assertEqual(self._get_env_value(env_text, "TRUSTED_PROXY_SOURCE_CIDRS"), "10.0.0.0/24")
        self.assertEqual(self._get_env_value(env_text, "OLLAMA_PULL_TIMEOUT_SECONDS"), "1800")
        self.assertEqual(self._get_env_value(env_text, "REDIS_IMAGE"), "redis@sha256:legacy")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_IMAGE"), "postgres@sha256:legacy")
        self.assertEqual(self._get_env_value(env_text, "OLLAMA_IMAGE"), "ollama/ollama@sha256:legacy")
        self.assertEqual(self._get_env_value(env_text, "NGINX_IMAGE"), "nginx@sha256:legacy")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_ENABLED"), "false")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_BOOTSTRAP_SCHEMA"), "false")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_SHADOW_COMPARE"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_THREADS"), "false")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_MESSAGES"), "false")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_DUAL_WRITE_CONVERSATION"), "false")
        self.assertEqual(
            self._get_env_value(env_text, "PERSISTENT_DB_URL"),
            "postgresql+psycopg://legacy_user:legacy_pw@postgres:5432/legacy_db",
        )

    def test_existing_env_preserves_dashboard_allowlist(self):
        existing_env = textwrap.dedent(
            """
            ADMIN_DASHBOARD_USERS=alice, bob
            REDIS_PASSWORD=old-redis
            POSTGRES_DB=legacy_db
            POSTGRES_USER=legacy_user
            POSTGRES_PASSWORD=legacy_pw
            """
        ).strip()
        with tempfile.TemporaryDirectory() as temp_dir:
            env_text = self._run_write_env_file(temp_dir, existing_env=existing_env)

        self.assertEqual(self._get_env_value(env_text, "ADMIN_DASHBOARD_USERS"), "alice, bob")

    def test_compose_declares_postgres_service_and_volume(self):
        repo_root = Path(__file__).resolve().parents[1]
        compose_text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("postgres:", compose_text)
        self.assertIn("image: ${POSTGRES_IMAGE:-postgres@sha256:2586e2a95d1c9b31cb2967feb562948f7d364854453d703039b6efa45fe48417}", compose_text)
        self.assertIn("POSTGRES_DB: ${POSTGRES_DB:-corporate_ai}", compose_text)
        self.assertIn("POSTGRES_USER: ${POSTGRES_USER:-corporate_ai}", compose_text)
        self.assertIn("POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change-me-postgres}", compose_text)
        self.assertIn("postgres-data:/var/lib/postgresql/data", compose_text)
        self.assertIn("postgres-data:", compose_text)

    def test_generated_krb5_conf_disables_hostname_canonicalization_for_explicit_gssapi_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            krb5_text = self._run_write_krb5_conf(temp_dir, ldap_gssapi_service_host="srv-ad")

        self.assertIn("dns_canonicalize_hostname = false", krb5_text)

    def test_smoke_validation_user_allows_curated_installer_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_validate_smoke_test_model_contract(
                temp_dir,
                default_model="deepseek-r1:8b",
                test_admin_user="aitest",
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_curated_installer_catalog_is_loaded_from_registry_in_expected_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            records_text = self._run_hot_model_catalog_records(temp_dir)
            default_model = self._run_exported_default_model(temp_dir)

        keys = self._parse_hot_model_catalog_keys(records_text)
        self.assertEqual(
            keys,
            [
                "deepseek-r1:8b",
                "deepseek-r1:14b",
                "deepseek-r1:32b",
                "qwen3:8b",
                "qwen3:14b",
                "qwen3:30b",
                "gemma3:4b",
                "gemma3:12b",
                "llama3.1:8b",
                "llama3.1:70b",
                "mistral-small3.1",
            ],
        )
        self.assertEqual(default_model, "phi3:mini")
        self.assertNotEqual(default_model, keys[0])

    def test_non_installable_and_catalog_only_models_do_not_leak_into_installer_shortlist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            records_text = self._run_hot_model_catalog_records(temp_dir)

        keys = self._parse_hot_model_catalog_keys(records_text)
        self.assertNotIn("deepseek-coder:7b", keys)
        self.assertNotIn("gpt-oss:20b", keys)
        self.assertNotIn("qwen3.5:0.8b", keys)
        self.assertNotIn("phi3:mini", keys)
        self.assertNotIn("phi4-mini", keys)

    def test_smoke_validation_user_rejects_custom_model_outside_curated_catalog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_validate_smoke_test_model_contract(
                temp_dir,
                default_model="qwen2.5:7b",
                test_admin_user="aitest",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the installable installer catalog", result.stdout)

    def test_custom_model_stays_allowed_when_smoke_validation_user_is_not_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_validate_smoke_test_model_contract(
                temp_dir,
                default_model="qwen2.5:7b",
                test_admin_user="",
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()

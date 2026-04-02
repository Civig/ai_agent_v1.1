import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallPostgresProfileTests(unittest.TestCase):
    def _copy_install_fixture(self, temp_dir: str) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        for relative_path in ("install.sh", ".env.example", "docker-compose.yml"):
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
            DEFAULT_MODEL="phi3:mini"
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

    @staticmethod
    def _get_env_value(env_text: str, key: str) -> str | None:
        prefix = f"{key}="
        for line in env_text.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def test_fresh_install_profile_enables_postgres_conversation_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_text = self._run_write_env_file(temp_dir)

        self.assertEqual(self._get_env_value(env_text, "LDAP_GSSAPI_SERVICE_HOST"), "srv-ad")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_DB"), "corporate_ai")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_USER"), "corporate_ai")
        self.assertEqual(self._get_env_value(env_text, "POSTGRES_PASSWORD"), "postgres-secret")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_ENABLED"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_BOOTSTRAP_SCHEMA"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_DUAL_WRITE_CONVERSATION"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_THREADS"), "true")
        self.assertEqual(self._get_env_value(env_text, "PERSISTENT_DB_READ_MESSAGES"), "true")
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

    def test_compose_declares_postgres_service_and_volume(self):
        repo_root = Path(__file__).resolve().parents[1]
        compose_text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("postgres:", compose_text)
        self.assertIn("image: postgres:16", compose_text)
        self.assertIn("POSTGRES_DB: ${POSTGRES_DB:-corporate_ai}", compose_text)
        self.assertIn("POSTGRES_USER: ${POSTGRES_USER:-corporate_ai}", compose_text)
        self.assertIn("POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-change-me-postgres}", compose_text)
        self.assertIn("postgres-data:/var/lib/postgresql/data", compose_text)
        self.assertIn("postgres-data:", compose_text)


if __name__ == "__main__":
    unittest.main()

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallStandaloneChatContractTests(unittest.TestCase):
    def _copy_install_fixture(self, temp_dir: str) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "install.sh",
            ".env.example",
            "docker-compose.yml",
        ):
            source_path = repo_root / relative_path
            target_path = Path(temp_dir) / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        return Path(temp_dir)

    def _run_install_shell(self, temp_dir: str, shell_body: str) -> subprocess.CompletedProcess[str]:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            f"""
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            export INSTALL_HOST_STATE_DIR="$1/host-state"
            source ./install.sh
            as_root() {{
                "$@"
            }}
            {shell_body}
            """
        )
        return subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_example_env_has_no_default_standalone_chat_password(self):
        env_text = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(encoding="utf-8")

        self.assertIn("STANDALONE_CHAT_AUTH_ENABLED=false", env_text)
        self.assertIn("STANDALONE_CHAT_USERNAME=demo_ai", env_text)
        self.assertIn("STANDALONE_CHAT_PASSWORD_HASH=", env_text)
        self.assertNotIn("demo_ai:demo_ai", env_text)

    def test_docs_describe_standalone_test_chat_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        install_ru_text = repo_root.joinpath("docs", "INSTALL_ru.md").read_text(encoding="utf-8")
        security_ru_text = repo_root.joinpath("docs", "SECURITY_ru.md").read_text(encoding="utf-8")
        install_en_text = repo_root.joinpath("docs", "INSTALL_en.md").read_text(encoding="utf-8")
        security_en_text = repo_root.joinpath("docs", "SECURITY_en.md").read_text(encoding="utf-8")

        self.assertIn("STANDALONE_CHAT_AUTH_ENABLED=false", install_ru_text)
        self.assertIn("STANDALONE_CHAT_PASSWORD_HASH", install_ru_text)
        self.assertIn("standalone/test", install_ru_text)
        self.assertIn("standalone/test chat user", security_en_text)
        self.assertIn("hash-only", security_en_text)
        self.assertIn("STANDALONE_CHAT_FORCE_ROTATE", install_en_text)
        self.assertIn("STANDALONE_CHAT_BOOTSTRAP_REQUIRED", security_ru_text)

    def test_gpu_lab_auto_defaults_enable_standalone_chat_with_bootstrap_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                INSTALL_PROFILE="standalone_gpu_lab"
                export INSTALL_NONINTERACTIVE=1
                configure_standalone_chat_auth "./.env.missing"
                printf 'enabled=%s\\n' "${STANDALONE_CHAT_AUTH_ENABLED}"
                printf 'username=%s\\n' "${STANDALONE_CHAT_USERNAME}"
                printf 'hash_present=%s\\n' "$(test -n "${STANDALONE_CHAT_PASSWORD_HASH}" && printf yes || printf no)"
                printf 'force_rotate=%s\\n' "${STANDALONE_CHAT_FORCE_ROTATE}"
                printf 'bootstrap_required=%s\\n' "${STANDALONE_CHAT_BOOTSTRAP_REQUIRED}"
                printf 'secret_file_exists=%s\\n' "$(test -f "${STANDALONE_CHAT_BOOTSTRAP_SECRET_FILE}" && printf yes || printf no)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("enabled=true", result.stdout)
        self.assertIn("username=demo_ai", result.stdout)
        self.assertIn("hash_present=yes", result.stdout)
        self.assertIn("force_rotate=true", result.stdout)
        self.assertIn("bootstrap_required=true", result.stdout)
        self.assertIn("secret_file_exists=yes", result.stdout)

    def test_explicit_standalone_chat_password_writes_only_hash_to_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                explicit_password="VeryLongStandaloneChatPassword-123"
                DOMAIN="corp.local"
                LDAP_SERVER_URL="ldap://srv-ad.corp.local"
                LDAP_GSSAPI_SERVICE_HOST="srv-ad"
                BASE_DN="DC=corp,DC=local"
                NETBIOS_DOMAIN="CORP"
                KERBEROS_REALM="CORP.LOCAL"
                KERBEROS_KDC="srv-ad.corp.local"
                SECRET_KEY="test-secret-key-1234567890-test-abcdef"
                SSO_ENABLED="false"
                SSO_SERVICE_PRINCIPAL=""
                SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
                LOCAL_ADMIN_ENABLED="false"
                LOCAL_ADMIN_USERNAME="admin_ai"
                LOCAL_ADMIN_PASSWORD_HASH=""
                LOCAL_ADMIN_FORCE_ROTATE="false"
                LOCAL_ADMIN_BOOTSTRAP_REQUIRED="false"
                STANDALONE_CHAT_AUTH_ENABLED="true"
                STANDALONE_CHAT_USERNAME="demo_ai"
                STANDALONE_CHAT_PASSWORD_HASH="$(build_standalone_chat_password_hash "${explicit_password}")"
                STANDALONE_CHAT_FORCE_ROTATE="false"
                STANDALONE_CHAT_BOOTSTRAP_REQUIRED="false"
                MODEL_ACCESS_CODING_GROUPS=""
                MODEL_ACCESS_ADMIN_GROUPS=""
                DEFAULT_MODEL="phi3:mini"
                REDIS_PASSWORD="redis-secret-123456"
                POSTGRES_DB="corporate_ai"
                POSTGRES_USER="corporate_ai"
                POSTGRES_PASSWORD="postgres-secret-123456"
                SELECTED_INSTALL_MODE="cpu"
                AD_SERVER_IP_OVERRIDE=""
                TEST_ADMIN_USER=""
                logical_hash="${STANDALONE_CHAT_PASSWORD_HASH}"
                write_env_file
                written_hash="$(grep '^STANDALONE_CHAT_PASSWORD_HASH=' .env | cut -d= -f2-)"
                runtime_hash="${written_hash//\\$\\$/\\$}"
                printf 'hash_written_compose_safe=%s\\n' "$(printf '%s' "${written_hash}" | grep -q '^pbkdf2_sha256\\$\\$' && printf yes || printf no)"
                printf 'runtime_hash_matches=%s\\n' "$(test "${runtime_hash}" = "${logical_hash}" && printf yes || printf no)"
                printf 'plaintext_in_env=%s\\n' "$(grep -F "${explicit_password}" .env >/dev/null && printf yes || printf no)"
                printf 'force_rotate=%s\\n' "$(grep '^STANDALONE_CHAT_FORCE_ROTATE=' .env | cut -d= -f2-)"
                printf 'bootstrap_required=%s\\n' "$(grep '^STANDALONE_CHAT_BOOTSTRAP_REQUIRED=' .env | cut -d= -f2-)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("hash_written_compose_safe=yes", result.stdout)
        self.assertIn("runtime_hash_matches=yes", result.stdout)
        self.assertIn("plaintext_in_env=no", result.stdout)
        self.assertIn("force_rotate=false", result.stdout)
        self.assertIn("bootstrap_required=false", result.stdout)

    def test_generated_bootstrap_secret_path_writes_root_only_secret_file_and_not_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                bootstrap_secret="generated-standalone-chat-bootstrap-123456789"
                DOMAIN="corp.local"
                LDAP_SERVER_URL="ldap://srv-ad.corp.local"
                LDAP_GSSAPI_SERVICE_HOST="srv-ad"
                BASE_DN="DC=corp,DC=local"
                NETBIOS_DOMAIN="CORP"
                KERBEROS_REALM="CORP.LOCAL"
                KERBEROS_KDC="srv-ad.corp.local"
                SECRET_KEY="test-secret-key-1234567890-test-abcdef"
                SSO_ENABLED="false"
                SSO_SERVICE_PRINCIPAL=""
                SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
                LOCAL_ADMIN_ENABLED="false"
                LOCAL_ADMIN_USERNAME="admin_ai"
                LOCAL_ADMIN_PASSWORD_HASH=""
                LOCAL_ADMIN_FORCE_ROTATE="false"
                LOCAL_ADMIN_BOOTSTRAP_REQUIRED="false"
                STANDALONE_CHAT_AUTH_ENABLED="true"
                STANDALONE_CHAT_USERNAME="demo_ai"
                STANDALONE_CHAT_PASSWORD_HASH="$(build_standalone_chat_password_hash "${bootstrap_secret}")"
                STANDALONE_CHAT_FORCE_ROTATE="true"
                STANDALONE_CHAT_BOOTSTRAP_REQUIRED="true"
                STANDALONE_CHAT_PLAINTEXT_SECRET="${bootstrap_secret}"
                MODEL_ACCESS_CODING_GROUPS=""
                MODEL_ACCESS_ADMIN_GROUPS=""
                DEFAULT_MODEL="phi3:mini"
                REDIS_PASSWORD="redis-secret-123456"
                POSTGRES_DB="corporate_ai"
                POSTGRES_USER="corporate_ai"
                POSTGRES_PASSWORD="postgres-secret-123456"
                SELECTED_INSTALL_MODE="cpu"
                AD_SERVER_IP_OVERRIDE=""
                TEST_ADMIN_USER=""
                logical_hash="${STANDALONE_CHAT_PASSWORD_HASH}"
                write_standalone_chat_bootstrap_secret_file "${STANDALONE_CHAT_PLAINTEXT_SECRET}"
                write_env_file
                written_hash="$(grep '^STANDALONE_CHAT_PASSWORD_HASH=' .env | cut -d= -f2-)"
                runtime_hash="${written_hash//\\$\\$/\\$}"
                printf 'secret_file_exists=%s\\n' "$(test -f "${STANDALONE_CHAT_BOOTSTRAP_SECRET_FILE}" && printf yes || printf no)"
                printf 'secret_file_mode=%s\\n' "$(stat -c '%a' "${STANDALONE_CHAT_BOOTSTRAP_SECRET_FILE}")"
                printf 'secret_file_contains_secret=%s\\n' "$(grep -F "${bootstrap_secret}" "${STANDALONE_CHAT_BOOTSTRAP_SECRET_FILE}" >/dev/null && printf yes || printf no)"
                printf 'hash_written_compose_safe=%s\\n' "$(printf '%s' "${written_hash}" | grep -q '^pbkdf2_sha256\\$\\$' && printf yes || printf no)"
                printf 'runtime_hash_matches=%s\\n' "$(test "${runtime_hash}" = "${logical_hash}" && printf yes || printf no)"
                printf 'plaintext_in_env=%s\\n' "$(grep -F "${bootstrap_secret}" .env >/dev/null && printf yes || printf no)"
                printf 'bootstrap_required=%s\\n' "$(grep '^STANDALONE_CHAT_BOOTSTRAP_REQUIRED=' .env | cut -d= -f2-)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("secret_file_exists=yes", result.stdout)
        self.assertIn("secret_file_mode=600", result.stdout)
        self.assertIn("secret_file_contains_secret=yes", result.stdout)
        self.assertIn("hash_written_compose_safe=yes", result.stdout)
        self.assertIn("runtime_hash_matches=yes", result.stdout)
        self.assertIn("plaintext_in_env=no", result.stdout)
        self.assertIn("bootstrap_required=true", result.stdout)


if __name__ == "__main__":
    unittest.main()

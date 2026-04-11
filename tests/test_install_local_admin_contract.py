import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallLocalAdminContractTests(unittest.TestCase):
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

    def test_example_env_has_no_default_local_admin_password(self):
        env_text = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(encoding="utf-8")

        self.assertIn("LOCAL_ADMIN_ENABLED=false", env_text)
        self.assertIn("LOCAL_ADMIN_USERNAME=admin_ai", env_text)
        self.assertIn("LOCAL_ADMIN_PASSWORD_HASH=", env_text)
        self.assertNotIn("admin:admin", env_text)
        self.assertNotIn("LOCAL_ADMIN_PASSWORD_HASH=admin", env_text)

    def test_docs_describe_break_glass_local_admin_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        install_ru_text = repo_root.joinpath("docs", "INSTALL_ru.md").read_text(encoding="utf-8")
        security_ru_text = repo_root.joinpath("docs", "SECURITY_ru.md").read_text(encoding="utf-8")

        self.assertIn("LOCAL_ADMIN_ENABLED=false", install_ru_text)
        self.assertIn("LOCAL_ADMIN_PASSWORD_HASH", install_ru_text)
        self.assertIn("forced password rotation", install_ru_text)
        self.assertIn("root-only host file", install_ru_text)
        self.assertIn("local break-glass admin path", security_ru_text.lower())
        self.assertIn("LOCAL_ADMIN_FORCE_ROTATE", security_ru_text)
        self.assertIn("LOCAL_ADMIN_BOOTSTRAP_REQUIRED", security_ru_text)

    def test_noninteractive_defaults_keep_local_admin_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                export INSTALL_NONINTERACTIVE=1
                configure_local_admin_break_glass "./.env.missing"
                printf 'enabled=%s\\n' "${LOCAL_ADMIN_ENABLED}"
                printf 'username=%s\\n' "${LOCAL_ADMIN_USERNAME}"
                printf 'hash_present=%s\\n' "$(test -n "${LOCAL_ADMIN_PASSWORD_HASH}" && printf yes || printf no)"
                printf 'force_rotate=%s\\n' "${LOCAL_ADMIN_FORCE_ROTATE}"
                printf 'bootstrap_required=%s\\n' "${LOCAL_ADMIN_BOOTSTRAP_REQUIRED}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("enabled=false", result.stdout)
        self.assertIn("username=admin_ai", result.stdout)
        self.assertIn("hash_present=no", result.stdout)
        self.assertIn("force_rotate=false", result.stdout)
        self.assertIn("bootstrap_required=false", result.stdout)

    def test_explicit_local_admin_password_path_writes_only_hash_to_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                explicit_password="VeryLongExplicitLocalAdminPassword-123"
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
                LOCAL_ADMIN_ENABLED="true"
                LOCAL_ADMIN_USERNAME="admin_ai"
                LOCAL_ADMIN_PASSWORD_HASH="$(build_local_admin_password_hash "${explicit_password}")"
                LOCAL_ADMIN_FORCE_ROTATE="false"
                LOCAL_ADMIN_BOOTSTRAP_REQUIRED="false"
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
                logical_hash="${LOCAL_ADMIN_PASSWORD_HASH}"
                write_env_file
                written_hash="$(grep '^LOCAL_ADMIN_PASSWORD_HASH=' .env | cut -d= -f2-)"
                runtime_hash="${written_hash//\\$\\$/\\$}"
                printf 'hash_written_compose_safe=%s\\n' "$(printf '%s' "${written_hash}" | grep -q '^pbkdf2_sha256\\$\\$' && printf yes || printf no)"
                printf 'runtime_hash_matches=%s\\n' "$(test "${runtime_hash}" = "${logical_hash}" && printf yes || printf no)"
                printf 'plaintext_in_env=%s\\n' "$(grep -F "${explicit_password}" .env >/dev/null && printf yes || printf no)"
                printf 'force_rotate=%s\\n' "$(grep '^LOCAL_ADMIN_FORCE_ROTATE=' .env | cut -d= -f2-)"
                printf 'bootstrap_required=%s\\n' "$(grep '^LOCAL_ADMIN_BOOTSTRAP_REQUIRED=' .env | cut -d= -f2-)"
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
                bootstrap_secret="generated-bootstrap-secret-123456789"
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
                LOCAL_ADMIN_ENABLED="true"
                LOCAL_ADMIN_USERNAME="admin_ai"
                LOCAL_ADMIN_PASSWORD_HASH="$(build_local_admin_password_hash "${bootstrap_secret}")"
                LOCAL_ADMIN_FORCE_ROTATE="true"
                LOCAL_ADMIN_BOOTSTRAP_REQUIRED="true"
                LOCAL_ADMIN_PLAINTEXT_SECRET="${bootstrap_secret}"
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
                logical_hash="${LOCAL_ADMIN_PASSWORD_HASH}"
                write_local_admin_bootstrap_secret_file "${LOCAL_ADMIN_PLAINTEXT_SECRET}"
                write_env_file
                written_hash="$(grep '^LOCAL_ADMIN_PASSWORD_HASH=' .env | cut -d= -f2-)"
                runtime_hash="${written_hash//\\$\\$/\\$}"
                printf 'secret_file_exists=%s\\n' "$(test -f "${LOCAL_ADMIN_BOOTSTRAP_SECRET_FILE}" && printf yes || printf no)"
                printf 'secret_file_mode=%s\\n' "$(stat -c '%a' "${LOCAL_ADMIN_BOOTSTRAP_SECRET_FILE}")"
                printf 'secret_file_contains_secret=%s\\n' "$(grep -F "${bootstrap_secret}" "${LOCAL_ADMIN_BOOTSTRAP_SECRET_FILE}" >/dev/null && printf yes || printf no)"
                printf 'hash_written_compose_safe=%s\\n' "$(printf '%s' "${written_hash}" | grep -q '^pbkdf2_sha256\\$\\$' && printf yes || printf no)"
                printf 'runtime_hash_matches=%s\\n' "$(test "${runtime_hash}" = "${logical_hash}" && printf yes || printf no)"
                printf 'plaintext_in_env=%s\\n' "$(grep -F "${bootstrap_secret}" .env >/dev/null && printf yes || printf no)"
                printf 'bootstrap_required=%s\\n' "$(grep '^LOCAL_ADMIN_BOOTSTRAP_REQUIRED=' .env | cut -d= -f2-)"
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

    def test_existing_escaped_local_admin_hash_is_preserved_without_double_escaping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                bootstrap_secret="preserved-bootstrap-secret-123456789"
                logical_hash="$(build_local_admin_password_hash "${bootstrap_secret}")"
                escaped_hash="${logical_hash//\\$/\\$\\$}"
                cat > .env <<EOF
LOCAL_ADMIN_ENABLED=true
LOCAL_ADMIN_USERNAME=admin_ai
LOCAL_ADMIN_PASSWORD_HASH=${escaped_hash}
LOCAL_ADMIN_FORCE_ROTATE=true
LOCAL_ADMIN_BOOTSTRAP_REQUIRED=true
ENABLE_PARSER_STAGE=true
ENABLE_PARSER_PUBLIC_CUTOVER=true
FORWARDED_ALLOW_IPS=
TRUSTED_PROXY_SOURCE_CIDRS=127.0.0.1/32,::1/128
ADMIN_DASHBOARD_USERS=
OLLAMA_PULL_TIMEOUT_SECONDS=900
REDIS_IMAGE=redis@sha256:test
POSTGRES_IMAGE=postgres@sha256:test
OLLAMA_IMAGE=ollama/ollama@sha256:test
NGINX_IMAGE=nginx@sha256:test
POSTGRES_DB=corporate_ai
POSTGRES_USER=corporate_ai
POSTGRES_PASSWORD=postgres-secret-123456
PERSISTENT_DB_ENABLED=true
PERSISTENT_DB_URL=postgresql+psycopg://corporate_ai:postgres-secret-123456@postgres:5432/corporate_ai
PERSISTENT_DB_ECHO=false
PERSISTENT_DB_POOL_PRE_PING=true
PERSISTENT_DB_BOOTSTRAP_SCHEMA=true
PERSISTENT_DB_SHADOW_COMPARE=false
PERSISTENT_DB_READ_THREADS=true
PERSISTENT_DB_READ_MESSAGES=true
PERSISTENT_DB_DUAL_WRITE_CONVERSATION=true
EOF
                export INSTALL_NONINTERACTIVE=1
                configure_local_admin_break_glass "./.env"
                printf 'loaded_hash_matches_logical=%s\\n' "$(test "${LOCAL_ADMIN_PASSWORD_HASH}" = "${logical_hash}" && printf yes || printf no)"
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
                MODEL_ACCESS_CODING_GROUPS=""
                MODEL_ACCESS_ADMIN_GROUPS=""
                DEFAULT_MODEL="phi3:mini"
                REDIS_PASSWORD="redis-secret-123456"
                SELECTED_INSTALL_MODE="cpu"
                AD_SERVER_IP_OVERRIDE=""
                TEST_ADMIN_USER=""
                write_env_file
                rewritten_hash="$(grep '^LOCAL_ADMIN_PASSWORD_HASH=' .env | cut -d= -f2-)"
                printf 'rewritten_hash_matches_original_escaped=%s\\n' "$(test "${rewritten_hash}" = "${escaped_hash}" && printf yes || printf no)"
                printf 'rewritten_hash_double_escaped=%s\\n' "$(printf '%s' "${rewritten_hash}" | grep -q '\\$\\$\\$\\$' && printf yes || printf no)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("loaded_hash_matches_logical=yes", result.stdout)
        self.assertIn("rewritten_hash_matches_original_escaped=yes", result.stdout)
        self.assertIn("rewritten_hash_double_escaped=no", result.stdout)


if __name__ == "__main__":
    unittest.main()

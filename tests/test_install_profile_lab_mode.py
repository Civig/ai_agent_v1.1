import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallProfileLabModeTests(unittest.TestCase):
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

    @staticmethod
    def _get_env_value(env_text: str, key: str) -> str | None:
        prefix = f"{key}="
        for line in env_text.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def test_env_example_defaults_to_enterprise_ad_contract(self):
        env_text = Path(__file__).resolve().parents[1].joinpath(".env.example").read_text(encoding="utf-8")

        self.assertIn("INSTALL_PROFILE=enterprise", env_text)
        self.assertIn("AUTH_MODE=ad", env_text)
        self.assertIn("STANDALONE_CHAT_AUTH_ENABLED=false", env_text)
        self.assertIn("STANDALONE_CHAT_USERNAME=demo_ai", env_text)
        self.assertIn("STANDALONE_CHAT_PASSWORD_HASH=", env_text)
        self.assertIn("LAB_OPEN_AUTH_ACK=false", env_text)

    def test_profile_helper_maps_lab_profile_to_ad_and_skips_directory_requirements(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                printf 'enterprise_auth=%s\\n' "$(auth_mode_for_install_profile enterprise)"
                printf 'enterprise_directory=%s\\n' "$(install_profile_requires_directory_services enterprise && printf yes || printf no)"
                printf 'lab_auth=%s\\n' "$(auth_mode_for_install_profile standalone_gpu_lab)"
                printf 'lab_directory=%s\\n' "$(install_profile_requires_directory_services standalone_gpu_lab && printf yes || printf no)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("enterprise_auth=ad", result.stdout)
        self.assertIn("enterprise_directory=yes", result.stdout)
        self.assertIn("lab_auth=ad", result.stdout)
        self.assertIn("lab_directory=no", result.stdout)

    def test_select_install_profile_and_mode_force_gpu_lab_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                INSTALL_PROFILE="enterprise"
                INSTALL_NONINTERACTIVE="1"
                select_install_profile
                select_install_mode
                printf 'profile=%s\\n' "${INSTALL_PROFILE}"
                printf 'auth=%s\\n' "${AUTH_MODE}"
                printf 'ack=%s\\n' "${LAB_OPEN_AUTH_ACK}"
                printf 'mode=%s\\n' "${SELECTED_INSTALL_MODE}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("profile=standalone_gpu_lab", result.stdout)
        self.assertIn("auth=ad", result.stdout)
        self.assertIn("ack=false", result.stdout)
        self.assertIn("mode=gpu", result.stdout)

    def test_gpu_lab_auto_configures_bootstrap_dashboard_admin_and_frontend_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                INSTALL_PROFILE="standalone_gpu_lab"
                configure_local_admin_break_glass "./.env.missing"
                configure_standalone_chat_auth "./.env.missing"
                printf 'local_admin_enabled=%s\\n' "${LOCAL_ADMIN_ENABLED}"
                printf 'local_admin_username=%s\\n' "${LOCAL_ADMIN_USERNAME}"
                printf 'local_admin_hash_present=%s\\n' "$(test -n "${LOCAL_ADMIN_PASSWORD_HASH}" && printf yes || printf no)"
                printf 'local_admin_force_rotate=%s\\n' "${LOCAL_ADMIN_FORCE_ROTATE}"
                printf 'local_admin_bootstrap_required=%s\\n' "${LOCAL_ADMIN_BOOTSTRAP_REQUIRED}"
                printf 'local_admin_secret_file=%s\\n' "$(test -f "${LOCAL_ADMIN_BOOTSTRAP_SECRET_FILE}" && printf yes || printf no)"
                printf 'standalone_enabled=%s\\n' "${STANDALONE_CHAT_AUTH_ENABLED}"
                printf 'standalone_username=%s\\n' "${STANDALONE_CHAT_USERNAME}"
                printf 'standalone_hash_present=%s\\n' "$(test -n "${STANDALONE_CHAT_PASSWORD_HASH}" && printf yes || printf no)"
                printf 'standalone_force_rotate=%s\\n' "${STANDALONE_CHAT_FORCE_ROTATE}"
                printf 'standalone_bootstrap_required=%s\\n' "${STANDALONE_CHAT_BOOTSTRAP_REQUIRED}"
                printf 'standalone_secret_file=%s\\n' "$(test -f "${STANDALONE_CHAT_BOOTSTRAP_SECRET_FILE}" && printf yes || printf no)"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("local_admin_enabled=true", result.stdout)
        self.assertIn("local_admin_username=admin_ai", result.stdout)
        self.assertIn("local_admin_hash_present=yes", result.stdout)
        self.assertIn("local_admin_force_rotate=true", result.stdout)
        self.assertIn("local_admin_bootstrap_required=true", result.stdout)
        self.assertIn("local_admin_secret_file=yes", result.stdout)
        self.assertIn("standalone_enabled=true", result.stdout)
        self.assertIn("standalone_username=demo_ai", result.stdout)
        self.assertIn("standalone_hash_present=yes", result.stdout)
        self.assertIn("standalone_force_rotate=true", result.stdout)
        self.assertIn("standalone_bootstrap_required=true", result.stdout)
        self.assertIn("standalone_secret_file=yes", result.stdout)

    def test_write_env_file_writes_standalone_gpu_lab_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                INSTALL_PROFILE="enterprise"
                INSTALL_NONINTERACTIVE="1"
                select_install_profile
                select_install_mode
                DOMAIN="local.lab"
                LDAP_SERVER_URL="ldap://local.lab"
                LDAP_GSSAPI_SERVICE_HOST=""
                BASE_DN="dc=local,dc=lab"
                NETBIOS_DOMAIN="LOCAL"
                KERBEROS_REALM="LOCAL.LAB"
                KERBEROS_KDC="local.lab"
                SSO_ENABLED="false"
                SSO_SERVICE_PRINCIPAL=""
                SSO_KEYTAB_PATH="/etc/corporate-ai-sso/http.keytab"
                configure_local_admin_break_glass "./.env.missing"
                configure_standalone_chat_auth "./.env.missing"
                TEST_ADMIN_USER="${STANDALONE_CHAT_USERNAME}"
                TEST_ADMIN_PASSWORD="${STANDALONE_CHAT_PLAINTEXT_SECRET}"
                MODEL_ACCESS_CODING_GROUPS=""
                MODEL_ACCESS_ADMIN_GROUPS=""
                REDIS_PASSWORD="$(reuse_or_generate_secret "" generate_hex_secret)"
                POSTGRES_DB="corporate_ai"
                POSTGRES_USER="corporate_ai"
                POSTGRES_PASSWORD="$(reuse_or_generate_secret "" generate_hex_secret)"
                SECRET_KEY="$(reuse_or_generate_secret "" generate_base64_secret)"
                load_installer_model_records
                apply_installer_model_selection "1"
                DOWNLOAD_DEFAULT_MODEL_NOW="true"
                AD_SERVER_IP_OVERRIDE=""
                write_env_file
                cat .env
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        env_text = result.stdout
        self.assertEqual(self._get_env_value(env_text, "INSTALL_PROFILE"), "standalone_gpu_lab")
        self.assertEqual(self._get_env_value(env_text, "AUTH_MODE"), "ad")
        self.assertEqual(self._get_env_value(env_text, "LAB_OPEN_AUTH_ACK"), "false")
        self.assertEqual(self._get_env_value(env_text, "LOCAL_ADMIN_ENABLED"), "true")
        self.assertEqual(self._get_env_value(env_text, "LOCAL_ADMIN_FORCE_ROTATE"), "true")
        self.assertEqual(self._get_env_value(env_text, "LOCAL_ADMIN_BOOTSTRAP_REQUIRED"), "true")
        self.assertEqual(self._get_env_value(env_text, "STANDALONE_CHAT_AUTH_ENABLED"), "true")
        self.assertEqual(self._get_env_value(env_text, "STANDALONE_CHAT_USERNAME"), "demo_ai")
        self.assertTrue(bool(self._get_env_value(env_text, "STANDALONE_CHAT_PASSWORD_HASH")))
        self.assertEqual(self._get_env_value(env_text, "STANDALONE_CHAT_FORCE_ROTATE"), "true")
        self.assertEqual(self._get_env_value(env_text, "STANDALONE_CHAT_BOOTSTRAP_REQUIRED"), "true")
        self.assertEqual(self._get_env_value(env_text, "SSO_ENABLED"), "false")
        self.assertEqual(self._get_env_value(env_text, "TRUSTED_AUTH_PROXY_ENABLED"), "false")
        self.assertEqual(self._get_env_value(env_text, "GPU_ENABLED"), "true")
        self.assertEqual(self._get_env_value(env_text, "INSTALL_TEST_USER"), "demo_ai")

    def test_gpu_mode_override_adds_ollama_gpu_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                SELECTED_INSTALL_MODE="gpu"
                AD_SERVER_IP_OVERRIDE=""
                LDAP_SERVER_HOST="dc01.example.local"
                KERBEROS_KDC="dc01.example.local"
                write_compose_override_if_needed
                cat docker-compose.override.yml
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        override_text = result.stdout
        self.assertIn("# Managed by Corporate AI Assistant install.sh", override_text)
        self.assertIn("  ollama:", override_text)
        self.assertIn("    gpus: all", override_text)
        self.assertIn("      NVIDIA_VISIBLE_DEVICES: all", override_text)
        self.assertIn("      NVIDIA_DRIVER_CAPABILITIES: compute,utility", override_text)
        self.assertNotIn("extra_hosts", override_text)

    def test_gpu_mode_override_combines_ollama_gpu_and_ad_host_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                SELECTED_INSTALL_MODE="gpu"
                AD_SERVER_IP_OVERRIDE="10.10.10.10"
                LDAP_SERVER_HOST="dc01.example.local"
                KERBEROS_KDC="kdc01.example.local"
                write_compose_override_if_needed
                cat docker-compose.override.yml
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        override_text = result.stdout
        self.assertIn("  ollama:", override_text)
        self.assertIn("    gpus: all", override_text)
        self.assertIn("  app:", override_text)
        self.assertIn("  worker-gpu:", override_text)
        self.assertIn("      dc01: '10.10.10.10'", override_text)
        self.assertIn("      dc01.example.local: '10.10.10.10'", override_text)
        self.assertIn("      kdc01: '10.10.10.10'", override_text)
        self.assertIn("      kdc01.example.local: '10.10.10.10'", override_text)

    def test_cpu_mode_without_ad_override_does_not_write_installer_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                SELECTED_INSTALL_MODE="cpu"
                AD_SERVER_IP_OVERRIDE=""
                LDAP_SERVER_HOST="dc01.example.local"
                KERBEROS_KDC="dc01.example.local"
                write_compose_override_if_needed
                if [[ -f docker-compose.override.yml ]]; then
                    printf 'override_present=yes\\n'
                else
                    printf 'override_present=no\\n'
                fi
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("override_present=no", result.stdout)

    def test_install_script_keeps_enterprise_ad_prompts_and_mentions_lab_profile(self):
        script_text = Path(__file__).resolve().parents[1].joinpath("install.sh").read_text(encoding="utf-8")

        self.assertIn("AD domain / Домен AD", script_text)
        self.assertIn("LDAP server hostname or FQDN", script_text)
        self.assertIn("Standalone GPU Lab install", script_text)


if __name__ == "__main__":
    unittest.main()

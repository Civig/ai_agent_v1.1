import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallOfflineRepairContractTests(unittest.TestCase):
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

    def _run_shell(self, temp_dir: str, shell_body: str) -> subprocess.CompletedProcess[str]:
        temp_root = self._copy_install_fixture(temp_dir)
        shell_script = textwrap.dedent(
            f"""
            set -Eeuo pipefail
            cd "$1"
            export INSTALL_SH_SOURCE_ONLY=1
            source ./install.sh
            {shell_body}
            """
        )
        return subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_fresh_install_without_network_still_fails_early(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                AUDIT_OUTBOUND_DOCKER_DOWNLOAD="failed"
                AUDIT_OUTBOUND_DOCKER_REGISTRY="failed"
                AUDIT_OUTBOUND_OLLAMA="failed"
                AUDIT_OUTBOUND_PYPI="failed"
                network_check
                """,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fresh install/bootstrap still requires outbound network", result.stdout)

    def test_existing_installation_can_enter_post_deploy_local_repair_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                : > .env
                mkdir -p .install
                : > .install/install-state.env
                command_exists() {
                    if [[ "$1" == "docker" ]]; then
                        return 0
                    fi
                    builtin command -v "$1" >/dev/null 2>&1
                }
                docker() {
                    if [[ "$1" == "compose" && "$2" == "version" ]]; then
                        return 0
                    fi
                    return 0
                }
                AUDIT_OUTBOUND_DOCKER_DOWNLOAD="failed"
                AUDIT_OUTBOUND_DOCKER_REGISTRY="failed"
                AUDIT_OUTBOUND_OLLAMA="failed"
                AUDIT_OUTBOUND_PYPI="failed"
                network_check
                printf 'mode=%s\\n' "${POST_DEPLOY_LOCAL_REPAIR_MODE}"
                printf 'reason=%s\\n' "${POST_DEPLOY_LOCAL_REPAIR_REASON}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Continuing in post-deploy local repair mode", result.stdout)
        self.assertIn("mode=1", result.stdout)
        self.assertIn("reason=download.docker.com", result.stdout)

    def test_post_deploy_local_repair_refuses_missing_host_packages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                POST_DEPLOY_LOCAL_REPAIR_MODE="1"
                append_unique_installed_package() { :; }
                dpkg() { return 1; }
                apt_install_if_missing curl
                """,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Post-deploy local repair mode cannot install missing host packages without outbound access",
            result.stdout,
        )

    def test_post_deploy_local_repair_skips_build_when_local_images_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                POST_DEPLOY_LOCAL_REPAIR_MODE="1"
                compose_required_local_images_present() { return 0; }
                docker_compose_for_install_mode() { printf 'compose:%s\\n' "$*" >> calls.log; }
                initialize_parser_staging_permissions() { printf 'init\\n' >> calls.log; }
                wait_for_ollama_container() { printf 'wait\\n' >> calls.log; }
                ensure_default_model_available() { printf 'model\\n' >> calls.log; }
                build_and_start_stack
                cat calls.log
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Skipping docker compose build in post-deploy local repair mode", result.stdout)
        self.assertNotIn("compose:build", result.stdout)
        self.assertIn("compose:up -d redis postgres ollama", result.stdout)
        self.assertIn("compose:up -d", result.stdout)

    def test_post_deploy_local_repair_fails_when_local_images_are_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                POST_DEPLOY_LOCAL_REPAIR_MODE="1"
                compose_required_local_images_present() { return 1; }
                build_and_start_stack
                """,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Post-deploy local repair mode requires all Docker Compose images to already exist locally",
            result.stdout,
        )

    def test_post_deploy_local_repair_does_not_require_host_ollama_cli(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_shell(
                temp_dir,
                """
                POST_DEPLOY_LOCAL_REPAIR_MODE="1"
                command_exists() {
                    if [[ "$1" == "ollama" ]]; then
                        return 1
                    fi
                    builtin command -v "$1" >/dev/null 2>&1
                }
                ensure_ollama_cli
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("post-deploy local repair mode will continue", result.stdout)

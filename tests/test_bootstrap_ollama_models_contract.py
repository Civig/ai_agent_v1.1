import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class BootstrapOllamaModelsContractTests(unittest.TestCase):
    def _copy_fixture(self, temp_dir: str) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "bootstrap_ollama_models.sh",
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

    def _run_bootstrap_shell(self, temp_dir: str, shell_body: str) -> subprocess.CompletedProcess[str]:
        temp_root = self._copy_fixture(temp_dir)
        shell_script = textwrap.dedent(
            f"""
            set -Eeuo pipefail
            cd "$1"
            export BOOTSTRAP_OLLAMA_SOURCE_ONLY=1
            source ./bootstrap_ollama_models.sh
            {shell_body}
            """
        )
        return subprocess.run(
            ["bash", "-lc", shell_script, "bash", str(temp_root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def _run_install_shell(self, temp_dir: str, shell_body: str) -> subprocess.CompletedProcess[str]:
        temp_root = self._copy_fixture(temp_dir)
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

    def test_pull_model_uses_bounded_retry_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                attempt_log="$(mktemp)"
                run_with_timeout() {
                    printf 'attempt\\n' >> "${attempt_log}"
                    return 124
                }
                sleep() { :; }
                set +e
                output="$(pull_model "phi3:mini" 2>&1)"
                status=$?
                set -e
                attempts="$(wc -l < "${attempt_log}")"
                printf 'status=%s\\n' "${status}"
                printf 'attempts=%s\\n' "${attempts}"
                printf '%s\\n' "${output}"
                rm -f "${attempt_log}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=124", result.stdout)
        self.assertIn("attempts=2", result.stdout)
        self.assertIn("Attempting to pull phi3:mini into Ollama (attempt 1/2", result.stdout)
        self.assertIn("Attempting to pull phi3:mini into Ollama (attempt 2/2", result.stdout)

    def test_main_succeeds_via_local_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                model_ready=0
                DEFAULT_MODEL="phi3:mini"
                LOCAL_GGUF="/tmp/offline-model.gguf"
                list_models() {
                    if [[ "${model_ready}" == "1" ]]; then
                        printf '%s\\n' "${DEFAULT_MODEL}"
                    fi
                }
                has_model() {
                    [[ "${model_ready}" == "1" && "$1" == "${DEFAULT_MODEL}" ]]
                }
                can_reach_ollama_registry() { return 1; }
                create_offline_model_from_gguf() {
                    model_ready=1
                    return 0
                }
                set +e
                output="$(main 2>&1)"
                status=$?
                set -e
                printf 'status=%s\\n' "${status}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=0", result.stdout)
        self.assertIn("available after local GGUF bootstrap", result.stdout)

    def test_main_fails_explicitly_when_pull_fails_and_no_local_asset_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                DEFAULT_MODEL="phi3:mini"
                LOCAL_GGUF=""
                list_models() { :; }
                has_model() { return 1; }
                can_reach_ollama_registry() { return 0; }
                pull_model() { return 124; }
                set +e
                output="$(main 2>&1)"
                status=$?
                set -e
                printf 'status=%s\\n' "${status}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=1", result.stdout)
        self.assertIn("Model bootstrap failed: bounded pull for phi3:mini did not complete successfully and no local GGUF asset is available", result.stdout)

    def test_main_succeeds_via_bounded_online_pull(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                model_ready=0
                DEFAULT_MODEL="phi3:mini"
                LOCAL_GGUF=""
                list_models() {
                    if [[ "${model_ready}" == "1" ]]; then
                        printf '%s\\n' "${DEFAULT_MODEL}"
                    fi
                }
                has_model() {
                    [[ "${model_ready}" == "1" && "$1" == "${DEFAULT_MODEL}" ]]
                }
                can_reach_ollama_registry() { return 0; }
                pull_model() {
                    model_ready=1
                    return 0
                }
                set +e
                output="$(main 2>&1)"
                status=$?
                set -e
                printf 'status=%s\\n' "${status}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=0", result.stdout)
        self.assertIn("available after bounded online bootstrap", result.stdout)

    def test_install_uses_bootstrap_script_contract_without_exec_bit_dependency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                DEFAULT_MODEL="phi3:mini"
                DOWNLOAD_DEFAULT_MODEL_NOW="true"
                printf '%s\n' \
                    '#!/usr/bin/env bash' \
                    'set -euo pipefail' \
                    ': > .bootstrap-called' \
                    ': > .default-model-ready' \
                    > ./bootstrap_ollama_models.sh
                chmod 0644 ./bootstrap_ollama_models.sh
                docker_compose() {
                    if [[ "$1" == "exec" && "$2" == "-T" && "$3" == "ollama" && "$4" == "ollama" && "$5" == "list" ]]; then
                        if [[ -f .default-model-ready ]]; then
                            printf 'NAME ID SIZE MODIFIED\\n'
                            printf '%s 1 1B just-now\\n' "${DEFAULT_MODEL}"
                        else
                            printf 'NAME ID SIZE MODIFIED\\n'
                        fi
                        return 0
                    fi
                    return 0
                }
                ensure_default_model_available
                printf 'bootstrap_executable=%s\\n' "$(test -x ./bootstrap_ollama_models.sh && printf yes || printf no)"
                printf 'bootstrap_called=%s\\n' "$(test -f .bootstrap-called && printf yes || printf no)"
                printf 'model_status=%s\\n' "${MODEL_BOOTSTRAP_STATUS}"
                printf 'model_present=%s\\n' "${MODEL_PRESENT_AFTER_BOOTSTRAP}"
                printf 'chat_ready=%s\\n' "${CHAT_READY_IMMEDIATELY}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("bootstrap_executable=no", result.stdout)
        self.assertIn("bootstrap_called=yes", result.stdout)
        self.assertIn("model_status=done", result.stdout)
        self.assertIn("model_present=yes", result.stdout)
        self.assertIn("chat_ready=yes", result.stdout)

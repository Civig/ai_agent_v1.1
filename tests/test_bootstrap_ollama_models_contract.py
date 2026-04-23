import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.model_contract_test_helper import exported_canonical_default_model


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

    def _run_exported_default_model(self, temp_dir: str) -> str:
        temp_root = self._copy_fixture(temp_dir)
        return exported_canonical_default_model(temp_root)

    def test_pull_model_uses_bounded_retry_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                attempt_log="$(mktemp)"
                default_model="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
                run_with_timeout() {
                    printf 'attempt\\n' >> "${attempt_log}"
                    return 124
                }
                sleep() { :; }
                set +e
                output="$(pull_model "${default_model}" 2>&1)"
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
        self.assertIn(f"Attempting to pull {expected_default_model} into Ollama (attempt 1/2", result.stdout)
        self.assertIn(f"Attempting to pull {expected_default_model} into Ollama (attempt 2/2", result.stdout)

    def test_bootstrap_uses_exported_canonical_default_when_env_default_is_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = self._copy_fixture(temp_dir)
            expected_default_model = exported_canonical_default_model(temp_root)
            shell_script = textwrap.dedent(
                """
                set -Eeuo pipefail
                cd "$1"
                unset DEFAULT_MODEL
                export BOOTSTRAP_OLLAMA_SOURCE_ONLY=1
                source ./bootstrap_ollama_models.sh
                printf 'default=%s\\n' "${DEFAULT_MODEL}"
                """
            )
            result = subprocess.run(
                ["bash", "-lc", shell_script, "bash", str(temp_root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(f"default={expected_default_model}", result.stdout)

    def test_has_model_accepts_short_alias_when_latest_tag_is_live(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                list_models() {
                    printf 'mistral:latest\\n'
                    printf 'qwen2.5:14b\\n'
                }
                set +e
                has_model "mistral"
                short_status=$?
                has_model "qwen2.5:14b"
                explicit_status=$?
                has_model "qwen2.5"
                missing_status=$?
                set -e
                printf 'short=%s\\n' "${short_status}"
                printf 'explicit=%s\\n' "${explicit_status}"
                printf 'missing=%s\\n' "${missing_status}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("short=0", result.stdout)
        self.assertIn("explicit=0", result.stdout)
        self.assertIn("missing=1", result.stdout)

    def test_installer_presence_check_accepts_short_alias_when_latest_tag_is_live(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                DEFAULT_MODEL="mistral"
                SELECTED_INSTALLER_MODELS="mistral"
                SELECTED_SECONDARY_MODELS=""
                DOWNLOAD_DEFAULT_MODEL_NOW="true"
                docker_compose() {
                    if [[ "$*" == "exec -T ollama ollama list" ]]; then
                        printf 'NAME ID SIZE MODIFIED\\n'
                        printf 'mistral:latest abc 4.4GB now\\n'
                        return 0
                    fi
                    return 1
                }
                output_file="$(mktemp)"
                set +e
                ensure_default_model_available >"${output_file}" 2>&1
                status=$?
                set -e
                output="$(cat "${output_file}")"
                rm -f "${output_file}"
                printf 'status=%s\\n' "${status}"
                printf 'bootstrap_status=%s\\n' "${MODEL_BOOTSTRAP_STATUS}"
                printf 'present=%s\\n' "${MODEL_PRESENT_AFTER_BOOTSTRAP}"
                printf 'ready=%s\\n' "${CHAT_READY_IMMEDIATELY}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=0", result.stdout)
        self.assertIn("bootstrap_status=already-present", result.stdout)
        self.assertIn("present=yes", result.stdout)
        self.assertIn("ready=yes", result.stdout)

    def test_main_succeeds_via_local_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                model_ready=0
                DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
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
        self.assertIn(expected_default_model, result.stdout)

    def test_main_fails_explicitly_when_pull_fails_and_no_local_asset_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
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
        self.assertIn(
            f"Model bootstrap failed: bounded pull for {expected_default_model} did not complete successfully and no local GGUF asset is available",
            result.stdout,
        )

    def test_main_succeeds_via_bounded_online_pull(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                model_ready=0
                DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
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
        self.assertIn(expected_default_model, result.stdout)

    def test_main_bootstraps_selected_secondary_models_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_bootstrap_shell(
                temp_dir,
                """
                available_models=""
                DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
                SECONDARY_MODELS="gemma2:2b,codellama:13b"
                list_models() {
                    local model=""
                    for model in ${available_models}; do
                        printf '%s\\n' "${model}"
                    done
                }
                has_model() {
                    [[ " ${available_models} " == *" $1 "* ]]
                }
                can_reach_ollama_registry() { return 0; }
                pull_model() {
                    if [[ "$1" == "${DEFAULT_MODEL}" || "$1" == "gemma2:2b" ]]; then
                        available_models="${available_models} $1"
                        return 0
                    fi
                    return 1
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
        self.assertIn(f"BOOTSTRAP_SUMMARY|successful|{expected_default_model},gemma2:2b", result.stdout)
        self.assertIn("BOOTSTRAP_SUMMARY|failed|codellama:13b", result.stdout)
        self.assertIn("BOOTSTRAP_FAILURE_DETAIL|codellama:13b|pull exited with status 1", result.stdout)

    def test_install_uses_bootstrap_script_contract_without_exec_bit_dependency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_install_shell(
                temp_dir,
                """
                DEFAULT_MODEL="$(python3 ./tools/export_installer_model_catalog.py --default-model ./models/catalog.json)"
                SELECTED_SECONDARY_MODELS="gemma2:2b,qwen2.5-coder:7b"
                DOWNLOAD_DEFAULT_MODEL_NOW="true"
                printf '%s\n' \
                    '#!/usr/bin/env bash' \
                    'set -euo pipefail' \
                    ': > .bootstrap-called' \
                    ': > .default-model-ready' \
                    'printf "%s\\n" "${SECONDARY_MODELS:-}" > .secondary-models' \
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
                printf 'secondary_models=%s\\n' "$(cat .secondary-models)"
                printf 'model_status=%s\\n' "${MODEL_BOOTSTRAP_STATUS}"
                printf 'model_present=%s\\n' "${MODEL_PRESENT_AFTER_BOOTSTRAP}"
                printf 'chat_ready=%s\\n' "${CHAT_READY_IMMEDIATELY}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("bootstrap_executable=no", result.stdout)
        self.assertIn("bootstrap_called=yes", result.stdout)
        self.assertIn("secondary_models=gemma2:2b,qwen2.5-coder:7b", result.stdout)
        self.assertIn("model_status=done", result.stdout)
        self.assertIn("model_present=yes", result.stdout)
        self.assertIn("chat_ready=yes", result.stdout)
        self.assertIn(expected_default_model, result.stdout)

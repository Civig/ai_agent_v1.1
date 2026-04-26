import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.model_contract_test_helper import exported_canonical_default_model


class InstallModelSelectionTests(unittest.TestCase):
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
        temp_root = self._copy_install_fixture(temp_dir)
        return exported_canonical_default_model(temp_root)

    def test_install_shell_resolves_canonical_default_from_exporter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_install_shell(
                temp_dir,
                """
                ensure_canonical_default_model
                printf 'default=%s\\n' "${DEFAULT_MODEL}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(f"default={expected_default_model}", result.stdout)

    def test_numeric_single_select_sets_default_without_secondary_models(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                load_installer_model_records
                apply_installer_model_selection "1"
                printf 'selected=%s\\n' "${SELECTED_INSTALLER_MODELS}"
                printf 'default=%s\\n' "${DEFAULT_MODEL}"
                printf 'secondary=%s\\n' "${SELECTED_SECONDARY_MODELS:-<none>}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("selected=deepseek-r1:8b", result.stdout)
        self.assertIn("default=deepseek-r1:8b", result.stdout)
        self.assertIn("secondary=<none>", result.stdout)

    def test_numeric_multi_select_preserves_order_and_sets_default_and_secondary_models(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                load_installer_model_records
                apply_installer_model_selection "1,2,5"
                printf 'selected=%s\\n' "${SELECTED_INSTALLER_MODELS}"
                printf 'default=%s\\n' "${DEFAULT_MODEL}"
                printf 'secondary=%s\\n' "${SELECTED_SECONDARY_MODELS}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("selected=deepseek-r1:8b,deepseek-r1:14b,qwen3:14b", result.stdout)
        self.assertIn("default=deepseek-r1:8b", result.stdout)
        self.assertIn("secondary=deepseek-r1:14b,qwen3:14b", result.stdout)

    def test_numeric_multi_select_trims_spaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                load_installer_model_records
                mapfile -t selected_models < <(parse_numeric_model_selection "1, 2, 5")
                printf 'models=%s\\n' "$(IFS=,; printf '%s' "${selected_models[*]}")"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("models=deepseek-r1:8b,deepseek-r1:14b,qwen3:14b", result.stdout)

    def test_numeric_multi_select_rejects_invalid_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                load_installer_model_records
                set +e
                output="$(parse_numeric_model_selection "1,99" 2>&1)"
                status=$?
                set -e
                printf 'status=%s\\n' "${status}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=1", result.stdout)
        self.assertIn("out of range", result.stdout)

    def test_numeric_multi_select_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._run_install_shell(
                temp_dir,
                """
                load_installer_model_records
                set +e
                output="$(parse_numeric_model_selection "1,2,2" 2>&1)"
                status=$?
                set -e
                printf 'status=%s\\n' "${status}"
                printf '%s\\n' "${output}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("status=1", result.stdout)
        self.assertIn("Duplicate model selection number", result.stdout)

    def test_custom_model_prompt_preserves_exact_existing_default_via_custom_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_default_model = self._run_exported_default_model(temp_dir)
            result = self._run_install_shell(
                temp_dir,
                f"""
                is_interactive_shell() {{
                    return 0
                }}
                SELECTED_INSTALL_MODE="cpu"
                INSTALL_PROFILE="enterprise"
                custom_choice="$(installer_custom_choice_number)"
                prompt_input="$(printf '%s\\n\\n%s\\n' "${{custom_choice}}" "n")"
                prompt_default_model_selection "{expected_default_model}" <<< "${{prompt_input}}"
                printf 'selected=%s\\n' "${{SELECTED_INSTALLER_MODELS}}"
                printf 'default=%s\\n' "${{DEFAULT_MODEL}}"
                printf 'secondary=%s\\n' "${{SELECTED_SECONDARY_MODELS:-<none>}}"
                printf 'download=%s\\n' "${{DOWNLOAD_DEFAULT_MODEL_NOW}}"
                """,
            )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn(f"selected={expected_default_model}", result.stdout)
        self.assertIn(f"default={expected_default_model}", result.stdout)
        self.assertIn("secondary=<none>", result.stdout)
        self.assertIn("download=false", result.stdout)


if __name__ == "__main__":
    unittest.main()

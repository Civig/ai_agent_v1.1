import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


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
        self.assertIn("selected=phi3:mini", result.stdout)
        self.assertIn("default=phi3:mini", result.stdout)
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
        self.assertIn("selected=phi3:mini,gemma2:2b,llama3.1:8b", result.stdout)
        self.assertIn("default=phi3:mini", result.stdout)
        self.assertIn("secondary=gemma2:2b,llama3.1:8b", result.stdout)

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
        self.assertIn("models=phi3:mini,gemma2:2b,llama3.1:8b", result.stdout)

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


if __name__ == "__main__":
    unittest.main()

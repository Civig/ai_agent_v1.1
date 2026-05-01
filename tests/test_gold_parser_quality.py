import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from typing import Any


os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import parser_stage


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "smoke" / "fixtures" / "gold" / "manifest.json"

REQUIRED_SUCCESS_IDS = {
    "txt_entities_alpha_bravo_charlie",
    "txt_parameters_parser_budget",
    "csv_orders_contract_status",
    "xlsx_orders_and_metrics",
    "docx_project_helios_table",
    "pdf_text_layer_entities",
    "pdf_text_layer_parameters",
}
REQUIRED_FAILURE_IDS = {
    "pdf_scanned_no_text_layer",
    "pdf_malformed_payload",
    "docx_missing_document_xml",
    "xls_unsupported_legacy_workbook",
}
OPTIONAL_OCR_IDS = {
    "png_ocr_success_alpha_score",
}

CONTENT_TYPES = {
    "txt": "text/plain",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "xls": "application/vnd.ms-excel",
}


def scalar_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(scalar_strings(nested))
        return values
    if isinstance(value, list):
        values = []
        for nested in value:
            values.extend(scalar_strings(nested))
        return values
    return []


class GoldParserQualityTests(unittest.TestCase):
    def load_manifest_entries(self) -> dict[str, dict[str, Any]]:
        with MANIFEST_PATH.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        return {entry["id"]: entry for entry in manifest["fixtures"]}

    def fixture_path(self, entry: dict[str, Any]) -> Path:
        relative_path = Path(entry["path"])
        self.assertFalse(relative_path.is_absolute(), entry["id"])
        self.assertNotIn("..", relative_path.parts, entry["id"])
        path = (REPO_ROOT / relative_path).resolve()
        path.relative_to(REPO_ROOT.resolve())
        return path

    def parse_uploaded_file(self, entry: dict[str, Any]) -> str:
        # pypdf can write diagnostics for intentionally malformed PDFs; keep unittest output stable.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return parser_stage.parse_uploaded_file(self.fixture_path(entry))

    def expected_terms(self, entry: dict[str, Any]) -> list[str]:
        terms = list(entry["expected_entities"])
        terms.extend(scalar_strings(entry["expected_values"]))
        return terms

    def assert_upload_mime_contract(self, entry: dict[str, Any]) -> None:
        path = self.fixture_path(entry)
        content_type = CONTENT_TYPES[entry["format"]]
        allowed = parser_stage.upload_content_type_is_allowed(path.suffix.lower(), content_type)
        if entry["format"] == "xls":
            self.assertFalse(allowed, entry["id"])
        else:
            self.assertTrue(allowed, entry["id"])

    def test_parser_quality_selection_covers_manifest_explicitly(self) -> None:
        entries = self.load_manifest_entries()
        selected_ids = REQUIRED_SUCCESS_IDS | REQUIRED_FAILURE_IDS | OPTIONAL_OCR_IDS

        self.assertEqual(set(entries), selected_ids)
        for entry_id in REQUIRED_SUCCESS_IDS:
            self.assertEqual(entries[entry_id]["expected_status"], "success", entry_id)
        for entry_id in REQUIRED_FAILURE_IDS:
            self.assertEqual(entries[entry_id]["expected_status"], "failure", entry_id)
        for entry_id in OPTIONAL_OCR_IDS:
            self.assertIn(entries[entry_id]["format"], {"png", "jpg", "jpeg"}, entry_id)

    def test_success_entries_parse_and_contain_manifest_expectations(self) -> None:
        entries = self.load_manifest_entries()

        for entry_id in sorted(REQUIRED_SUCCESS_IDS):
            entry = entries[entry_id]
            with self.subTest(entry_id=entry_id):
                self.assert_upload_mime_contract(entry)

                extracted_text = self.parse_uploaded_file(entry)

                self.assertTrue(extracted_text.strip(), entry_id)
                for term in self.expected_terms(entry):
                    self.assertIn(term, extracted_text, f"{entry_id} missing {term!r}")

    def test_failure_entries_raise_manifest_controlled_errors(self) -> None:
        entries = self.load_manifest_entries()

        for entry_id in sorted(REQUIRED_FAILURE_IDS):
            entry = entries[entry_id]
            with self.subTest(entry_id=entry_id):
                self.assert_upload_mime_contract(entry)

                with self.assertRaises(Exception) as error:
                    self.parse_uploaded_file(entry)

                self.assertIn(entry["expected_controlled_error_substring"], str(error.exception), entry_id)

    def test_ocr_success_entries_are_not_required_parser_quality_passes(self) -> None:
        entries = self.load_manifest_entries()

        for entry_id in sorted(OPTIONAL_OCR_IDS):
            entry = entries[entry_id]
            with self.subTest(entry_id=entry_id):
                self.assertEqual(entry["expected_status"], "success")
                self.assertIn(entry["format"], {"png", "jpg", "jpeg"})
                self.assertIn("OCR", entry["notes"])
                self.assert_upload_mime_contract(entry)


if __name__ == "__main__":
    unittest.main()

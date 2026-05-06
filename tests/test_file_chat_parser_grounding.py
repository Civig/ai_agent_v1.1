from __future__ import annotations

import contextlib
import io
import os
import unittest
from pathlib import Path
from typing import Any

from scripts.smoke.smoke_common import REPO_ROOT, resolve_repo_path, validate_file_chat_cases


os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

SPEC_PATH = REPO_ROOT / "tests/smoke/specs/file_chat_cases.json"


class FileChatParserGroundingTests(unittest.TestCase):
    @classmethod
    def parser_stage_module(cls):
        try:
            import parser_stage  # type: ignore
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"parser_stage dependencies unavailable: {exc}") from exc
        return parser_stage

    def load_parser_cases(self) -> list[dict[str, Any]]:
        cases = validate_file_chat_cases(SPEC_PATH)
        return [case for case in cases if case.get("parser_expected_status")]

    def parse_case(self, case: dict[str, Any]) -> str:
        parser_stage = self.parser_stage_module()
        file_path = resolve_repo_path(str(case["file"]))
        self.assertTrue(file_path.is_file(), case["id"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return parser_stage.parse_uploaded_file(Path(file_path))

    def assert_terms_present(self, *, case: dict[str, Any], text: str) -> None:
        for term in case.get("parser_must_contain") or []:
            self.assertIn(str(term), text, f"{case['id']} parser output missing {term!r}")
        for term in case.get("parser_must_not_contain") or []:
            self.assertNotIn(str(term), text, f"{case['id']} parser output unexpectedly contained {term!r}")

    def test_file_chat_cases_define_separate_parser_expectations(self) -> None:
        parser_cases = self.load_parser_cases()

        self.assertGreaterEqual(len(parser_cases), 10)
        self.assertTrue(any(case["parser_expected_status"] == "known_gap" for case in parser_cases))
        self.assertTrue(any(case["parser_expected_status"] == "failure" for case in parser_cases))
        for case in parser_cases:
            self.assertIn(case["parser_expected_status"], {"success", "failure", "known_gap"}, case["id"])

    def test_success_cases_match_direct_parser_output(self) -> None:
        for case in self.load_parser_cases():
            if case["parser_expected_status"] != "success":
                continue
            with self.subTest(case_id=case["id"]):
                extracted_text = self.parse_case(case)

                self.assertTrue(extracted_text.strip(), case["id"])
                self.assert_terms_present(case=case, text=extracted_text)

    def test_failure_cases_raise_controlled_parser_errors(self) -> None:
        for case in self.load_parser_cases():
            if case["parser_expected_status"] != "failure":
                continue
            with self.subTest(case_id=case["id"]):
                self.parser_stage_module()
                with self.assertRaises(Exception) as error:
                    self.parse_case(case)

                detail = str(error.exception)
                for term in case.get("parser_error_must_contain") or []:
                    self.assertIn(str(term), detail, f"{case['id']} parser error missing {term!r}")

    def test_known_gap_cases_are_explicit_and_not_success(self) -> None:
        for case in self.load_parser_cases():
            if case["parser_expected_status"] != "known_gap":
                continue
            with self.subTest(case_id=case["id"]):
                reason = str(case.get("parser_known_gap_reason") or "").strip()
                self.assertTrue(reason, f"{case['id']} must explain the parser known gap")
                self.assertNotEqual(case["parser_expected_status"], "success", case["id"])

    def test_known_gap_direct_parser_output_still_has_expected_gap(self) -> None:
        for case in self.load_parser_cases():
            if case["parser_expected_status"] != "known_gap":
                continue
            with self.subTest(case_id=case["id"]):
                reason = str(case.get("parser_known_gap_reason") or "").strip()
                self.assertTrue(reason, f"{case['id']} must explain the parser known gap")

                try:
                    extracted_text = self.parse_case(case)
                except unittest.SkipTest:
                    raise
                except Exception as exc:
                    self.assertTrue(str(exc).strip(), f"{case['id']} parser known gap raised an empty error")
                    continue

                missing = [term for term in case.get("parser_must_contain") or [] if str(term) not in extracted_text]
                forbidden = [term for term in case.get("parser_must_not_contain") or [] if str(term) in extracted_text]
                if not missing and not forbidden:
                    self.fail(f"{case['id']} parser known gap now satisfies expectations; update the spec to success")


if __name__ == "__main__":
    unittest.main()

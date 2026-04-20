from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.smoke.smoke_common import (
    REPO_ROOT,
    build_load_summary,
    create_artifact_dir,
    evaluate_expectations,
    extract_cookie_from_netscape_cookiejar,
    parse_observability_line,
    read_password_file,
    validate_file_chat_cases,
)


class SmokeKitTests(unittest.TestCase):
    def test_file_chat_spec_has_required_machine_readable_fields(self) -> None:
        cases = validate_file_chat_cases(REPO_ROOT / "tests/smoke/specs/file_chat_cases.json")

        self.assertGreaterEqual(len(cases), 10)
        self.assertTrue(any(case["expected_status"] == "failure" for case in cases))
        for case in cases:
            self.assertTrue((REPO_ROOT / case["file"]).exists(), case["file"])

    def test_expectation_evaluator_checks_required_and_forbidden_text(self) -> None:
        case = {
            "expected_status": "success",
            "must_contain": ["ALPHA-17", "BRAVO-42"],
            "must_not_contain": ["DELTA-99"],
        }

        passed = evaluate_expectations(response_text="alpha-17 and BRAVO-42", case=case, actual_status="success")
        failed = evaluate_expectations(response_text="ALPHA-17 and DELTA-99", case=case, actual_status="success")

        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["missing"], ["BRAVO-42"])
        self.assertEqual(failed["forbidden"], ["DELTA-99"])

    def test_artifact_directory_creation_is_scoped_to_requested_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = create_artifact_dir(root, label="chat smoke")

            self.assertTrue(created.is_dir())
            self.assertEqual(created.parent, root)
            self.assertIn("chat-smoke", created.name)

    def test_cookiejar_csrf_extraction(self) -> None:
        cookiejar = "\n".join(
            [
                "# Netscape HTTP Cookie File",
                "127.0.0.1\tFALSE\t/\tFALSE\t0\tcsrf_token\tcsrf-value-123",
            ]
        )

        self.assertEqual(extract_cookie_from_netscape_cookiejar(cookiejar, "csrf_token"), "csrf-value-123")
        self.assertEqual(extract_cookie_from_netscape_cookiejar(cookiejar, "missing"), "")

    def test_observability_parser_keeps_wait_and_terminal_fields(self) -> None:
        row = parse_observability_line(
            "worker job_terminal_observability job_id=job-1 username=aitest "
            "queue_wait_ms=42 inference_ms=100 total_job_ms=150 terminal_status=completed"
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["event"], "job_terminal_observability")
        self.assertEqual(row["queue_wait_ms"], 42)
        self.assertEqual(row["pending_wait_ms"], 42)
        self.assertEqual(row["inference_ms"], 100)
        self.assertEqual(row["total_job_ms"], 150)

    def test_load_summary_percentiles_and_counts(self) -> None:
        summary = build_load_summary(
            [
                {"latency_ms": 100, "passed": True, "actual_status": "success"},
                {"latency_ms": 200, "passed": True, "actual_status": "success"},
                {"latency_ms": 400, "passed": False, "actual_status": "failure"},
            ],
            profile={"name": "unit"},
        )

        self.assertEqual(summary["total_requests"], 3)
        self.assertEqual(summary["successful_requests"], 2)
        self.assertEqual(summary["failed_requests"], 1)
        self.assertEqual(summary["p50_latency_ms"], 200.0)

    def test_password_file_parser_supports_bootstrap_secret_format(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write(
                "Corporate AI Assistant local break-glass admin bootstrap secret\n"
                "Username: admin_ai\n"
                "Secret: generated-bootstrap-secret-123456789\n"
            )
            handle.flush()

            self.assertEqual(read_password_file(handle.name), "generated-bootstrap-secret-123456789")


if __name__ == "__main__":
    unittest.main()

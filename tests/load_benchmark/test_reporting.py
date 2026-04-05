import json
import tempfile
import unittest
from pathlib import Path

from tests.load_benchmark.profiles import get_profile
from tests.load_benchmark.reporting import (
    RequestResult,
    build_summary,
    build_wait_rows,
    write_summary_json,
    write_wait_table_csv,
    write_wait_table_markdown,
)


class LoadBenchmarkReportingTests(unittest.TestCase):
    def test_build_summary_aggregates_latencies_and_health_peaks(self):
        profile = get_profile("5")
        results = [
            RequestResult(user_index=1, thread_id="bench-001", start_ms=100, end_ms=200, latency_ms=100, http_status=200, job_id="job-1", completed=True, final_text="OK"),
            RequestResult(user_index=2, thread_id="bench-002", start_ms=110, end_ms=260, latency_ms=150, http_status=200, job_id="job-2", completed=True, final_text="OK"),
            RequestResult(user_index=3, thread_id="bench-003", start_ms=120, end_ms=320, latency_ms=200, http_status=503, server_error=True, error_message="overload"),
        ]
        health_samples = [
            {"ts_ms": 1000, "payload": {"status": "not_ready", "capacity": False, "active_jobs": 1, "pending": {"chat:p1": 2}, "metrics": {"queue_depth": 2}}},
            {"ts_ms": 2000, "payload": {"status": "ready", "capacity": True, "active_jobs": 0, "pending": {"chat:p1": 0}, "metrics": {"queue_depth": 0}}},
        ]

        summary = build_summary(
            profile=profile,
            results=results,
            health_ready_samples=health_samples,
            measured_end_ms=1500,
            stop_condition_triggered="",
        )

        self.assertEqual(summary["profile_name"], "5")
        self.assertEqual(summary["total_requests"], 3)
        self.assertEqual(summary["successful_requests"], 2)
        self.assertEqual(summary["failed_requests"], 1)
        self.assertEqual(summary["accepted_requests"], 2)
        self.assertEqual(summary["accepted_completed_requests"], 2)
        self.assertEqual(summary["accepted_incomplete_requests"], 0)
        self.assertEqual(summary["max_queue_depth"], 2)
        self.assertEqual(summary["max_pending_chat_p1"], 2)
        self.assertEqual(summary["max_active_jobs"], 1)
        self.assertEqual(summary["capacity_false_samples"], 1)
        self.assertTrue(summary["drained"])
        self.assertEqual(summary["drain_seconds"], 0.5)
        self.assertEqual(summary["final_classification"], "completed_with_queue_pressure")

    def test_wait_table_and_summary_are_written_to_files(self):
        rows = build_wait_rows(
            [
                RequestResult(
                    user_index=1,
                    thread_id="bench-001",
                    start_ms=100,
                    end_ms=200,
                    latency_ms=100,
                    http_status=200,
                    job_id="job-1",
                    completed=True,
                    final_text="Ответ",
                )
            ]
        )
        summary = {"final_classification": "success", "total_requests": 1}

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            write_wait_table_csv(base / "wait_table.csv", rows)
            write_wait_table_markdown(base / "wait_table.md", rows)
            write_summary_json(base / "summary.json", summary)

            self.assertIn("bench-001", (base / "wait_table.csv").read_text(encoding="utf-8"))
            self.assertIn("| 1 | bench-001 |", (base / "wait_table.md").read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads((base / "summary.json").read_text(encoding="utf-8"))["final_classification"],
                "success",
            )


if __name__ == "__main__":
    unittest.main()

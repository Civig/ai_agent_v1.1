import unittest

from tests.load_benchmark.reporting import RequestResult, build_wait_rows


class LoadBenchmarkWaitTableTests(unittest.TestCase):
    def test_wait_rows_match_required_contract(self):
        rows = build_wait_rows(
            [
                RequestResult(
                    user_index=2,
                    thread_id="bench-002",
                    start_ms=200,
                    end_ms=350,
                    latency_ms=150,
                    http_status=200,
                    job_id="job-2",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=1,
                    thread_id="bench-001",
                    start_ms=100,
                    end_ms=180,
                    latency_ms=80,
                    http_status=200,
                    job_id="job-1",
                    completed=True,
                    final_text="OK",
                ),
            ]
        )

        self.assertEqual(rows[0]["user_index"], 1)
        self.assertEqual(rows[1]["thread_id"], "bench-002")
        self.assertEqual(
            list(rows[0].keys()),
            [
                "user_index",
                "thread_id",
                "start_ms",
                "end_ms",
                "latency_ms",
                "http_status",
                "job_id",
                "completed",
                "final_text_short",
            ],
        )


if __name__ == "__main__":
    unittest.main()

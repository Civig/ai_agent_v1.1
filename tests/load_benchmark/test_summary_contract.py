import unittest

from tests.load_benchmark.profiles import get_profile
from tests.load_benchmark.reporting import RequestResult, build_summary


class LoadBenchmarkSummaryContractTests(unittest.TestCase):
    def test_drained_success_uses_post_measured_steady_state_and_no_false_stuck(self):
        summary = build_summary(
            profile=get_profile("10"),
            results=[
                RequestResult(
                    user_index=1,
                    thread_id="bench-001",
                    start_ms=100,
                    end_ms=280,
                    latency_ms=180,
                    http_status=200,
                    job_id="job-1",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=2,
                    thread_id="bench-002",
                    start_ms=120,
                    end_ms=340,
                    latency_ms=220,
                    http_status=200,
                    job_id="job-2",
                    completed=True,
                    final_text="OK",
                ),
            ],
            health_ready_samples=[
                {"ts_ms": 900, "payload": {"status": "ready", "capacity": True, "active_jobs": 0, "pending": {"chat:p1": 0}, "metrics": {"queue_depth": 0}}},
                {"ts_ms": 1500, "payload": {"status": "not_ready", "capacity": False, "active_jobs": 2, "pending": {"chat:p1": 3}, "metrics": {"queue_depth": 3}}},
                {"ts_ms": 2600, "payload": {"status": "ready", "capacity": True, "active_jobs": 0, "pending": {"chat:p1": 0}, "metrics": {"queue_depth": 0}}},
            ],
            measured_end_ms=2000,
        )

        self.assertTrue(summary["drained"])
        self.assertEqual(summary["drain_seconds"], 0.6)
        self.assertEqual(summary["accepted_incomplete_requests"], 0)
        self.assertEqual(summary["final_classification"], "completed_with_queue_pressure")

    def test_rate_limit_tail_uses_request_latency_for_last_user_and_no_false_stuck(self):
        summary = build_summary(
            profile=get_profile("50"),
            results=[
                RequestResult(
                    user_index=1,
                    thread_id="bench-001",
                    start_ms=0,
                    end_ms=200,
                    latency_ms=200,
                    http_status=200,
                    job_id="job-1",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=2,
                    thread_id="bench-002",
                    start_ms=10,
                    end_ms=240,
                    latency_ms=230,
                    http_status=200,
                    job_id="job-2",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=50,
                    thread_id="bench-050",
                    start_ms=100,
                    end_ms=125,
                    latency_ms=25,
                    http_status=429,
                    rejected_429=True,
                    error_message="rate limit",
                ),
            ],
            health_ready_samples=[
                {"ts_ms": 1800, "payload": {"status": "not_ready", "capacity": False, "active_jobs": 2, "pending": {"chat:p1": 1}, "metrics": {"queue_depth": 1}}},
                {"ts_ms": 2600, "payload": {"status": "ready", "capacity": True, "active_jobs": 0, "pending": {"chat:p1": 0}, "metrics": {"queue_depth": 0}}},
            ],
            measured_end_ms=2000,
        )

        self.assertTrue(summary["drained"])
        self.assertEqual(summary["last_user_latency_ms"], 25)
        self.assertEqual(summary["last_completed_user_latency_ms"], 230)
        self.assertEqual(summary["rejected_429_count"], 1)
        self.assertEqual(summary["accepted_incomplete_requests"], 0)
        self.assertEqual(summary["final_classification"], "rate_limit_blocked")

    def test_latency_summary_keeps_request_and_completed_views_separate(self):
        summary = build_summary(
            profile=get_profile("20"),
            results=[
                RequestResult(
                    user_index=1,
                    thread_id="bench-001",
                    start_ms=0,
                    end_ms=100,
                    latency_ms=100,
                    http_status=200,
                    job_id="job-1",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=2,
                    thread_id="bench-002",
                    start_ms=10,
                    end_ms=210,
                    latency_ms=200,
                    http_status=200,
                    job_id="job-2",
                    completed=True,
                    final_text="OK",
                ),
                RequestResult(
                    user_index=3,
                    thread_id="bench-003",
                    start_ms=20,
                    end_ms=30,
                    latency_ms=10,
                    http_status=429,
                    rejected_429=True,
                    error_message="rate limit",
                ),
            ],
            health_ready_samples=[
                {"ts_ms": 1200, "payload": {"status": "ready", "capacity": True, "active_jobs": 0, "pending": {"chat:p1": 0}, "metrics": {"queue_depth": 0}}},
            ],
            measured_end_ms=1000,
        )

        self.assertEqual(summary["first_user_latency_ms"], 100)
        self.assertEqual(summary["median_user_latency_ms"], 100.0)
        self.assertEqual(summary["last_user_latency_ms"], 10)
        self.assertEqual(summary["first_completed_user_latency_ms"], 100)
        self.assertEqual(summary["median_completed_user_latency_ms"], 150.0)
        self.assertEqual(summary["last_completed_user_latency_ms"], 200)

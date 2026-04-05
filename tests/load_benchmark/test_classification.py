import unittest

from tests.load_benchmark.reporting import classify_run


class LoadBenchmarkClassificationTests(unittest.TestCase):
    def test_classify_success(self):
        self.assertEqual(
            classify_run(
                successful_requests=5,
                total_requests=5,
                timeout_count=0,
                rejected_429_count=0,
                auth_failure_count=0,
                drained=True,
                max_queue_depth=0,
                max_pending_chat_p1=0,
                capacity_false_samples=0,
                stop_condition_triggered="",
            ),
            "success",
        )

    def test_classify_rate_limit_block(self):
        self.assertEqual(
            classify_run(
                successful_requests=0,
                total_requests=50,
                timeout_count=0,
                rejected_429_count=50,
                auth_failure_count=0,
                drained=True,
                max_queue_depth=0,
                max_pending_chat_p1=0,
                capacity_false_samples=0,
                stop_condition_triggered="",
            ),
            "rate_limit_blocked",
        )

    def test_classify_timeout_block(self):
        self.assertEqual(
            classify_run(
                successful_requests=0,
                total_requests=20,
                timeout_count=20,
                rejected_429_count=0,
                auth_failure_count=0,
                drained=False,
                max_queue_depth=4,
                max_pending_chat_p1=4,
                capacity_false_samples=3,
                stop_condition_triggered="",
            ),
            "timeout_blocked",
        )

    def test_classify_auth_block(self):
        self.assertEqual(
            classify_run(
                successful_requests=0,
                total_requests=10,
                timeout_count=0,
                rejected_429_count=0,
                auth_failure_count=10,
                drained=True,
                max_queue_depth=0,
                max_pending_chat_p1=0,
                capacity_false_samples=0,
                stop_condition_triggered="",
            ),
            "auth_blocked",
        )


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class FakeRedis:
    async def ping(self):
        return False


class FakeDashboardGateway:
    def __init__(self):
        self.redis = FakeRedis()

    async def get_scheduler_status(self):
        return {"last_seen": 10}

    async def list_active_workers(self):
        return []

    async def list_working_workers(self, _workload_class=None):
        return []

    async def can_accept_workload(self, _workload_class=None):
        return False

    async def get_runtime_state(self):
        return {"pending": {"chat:p1": 2}, "active_jobs": 0, "targets": 0, "workers": 0}

    async def get_basic_metrics(self):
        return {
            "queue_depth": 2,
            "active_jobs": 0,
            "failed_jobs": 0,
            "rejected_jobs": 0,
            "job_latency_total_ms": 0,
            "job_latency_count": 0,
        }

    async def list_active_targets(self):
        return []


class AdminDashboardUnavailableMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_marks_unavailable_metrics_honestly(self):
        gateway = FakeDashboardGateway()

        with patch.object(app_module.time, "time", return_value=120):
            payload = await app_module.build_admin_dashboard_summary(gateway)

        self.assertEqual(payload["overall_status"], "degraded")
        self.assertEqual(payload["readiness_status"], "not_ready")
        self.assertEqual(payload["health_status"], "degraded")
        self.assertIsNone(payload["avg_latency_ms"])
        self.assertEqual(payload["active_models"], [])
        self.assertEqual(payload["chat_backlog"], 2)
        self.assertIn("Redis недоступен", payload["warnings"])
        self.assertIn("Свободная chat capacity недоступна", payload["warnings"])


if __name__ == "__main__":
    unittest.main()

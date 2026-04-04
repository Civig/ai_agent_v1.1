import json
import os
import unittest
from fastapi import FastAPI
from starlette.requests import Request
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class FakeRedis:
    def __init__(self, *, ok=True):
        self.ok = ok

    async def ping(self):
        return self.ok


class FakeDashboardGateway:
    def __init__(
        self,
        *,
        redis_ok=True,
        scheduler_status=None,
        active_workers=None,
        working_workers=None,
        active_targets=None,
        runtime_state=None,
        metrics=None,
        capacity=True,
    ):
        self.redis = FakeRedis(ok=redis_ok)
        self._scheduler_status = scheduler_status
        self._active_workers = list(active_workers or [])
        self._working_workers = list(working_workers or [])
        self._active_targets = list(active_targets or [])
        self._runtime_state = dict(runtime_state or {"pending": {}, "active_jobs": 0, "targets": 0, "workers": 0})
        self._metrics = dict(
            metrics
            or {
                "queue_depth": 0,
                "active_jobs": 0,
                "failed_jobs": 0,
                "rejected_jobs": 0,
                "job_latency_total_ms": 0,
                "job_latency_count": 0,
            }
        )
        self._capacity = capacity

    async def get_scheduler_status(self):
        return self._scheduler_status

    async def list_active_workers(self):
        return list(self._active_workers)

    async def list_working_workers(self, _workload_class=None):
        return list(self._working_workers)

    async def can_accept_workload(self, _workload_class=None):
        return self._capacity

    async def get_runtime_state(self):
        return dict(self._runtime_state)

    async def get_basic_metrics(self):
        return dict(self._metrics)

    async def list_active_targets(self):
        return list(self._active_targets)


def build_request(gateway) -> Request:
    app = FastAPI()
    app.state.llm_gateway = gateway
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/admin/dashboard/summary",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


class AdminDashboardAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_endpoint_returns_runtime_dashboard_shape(self):
        now_ts = 1_800_000_000
        gateway = FakeDashboardGateway(
            scheduler_status={"last_seen": now_ts - 2},
            active_workers=[
                {
                    "worker_id": "worker-chat-1",
                    "worker_pool": "chat",
                    "target_id": "ollama-main",
                    "target_kind": "cpu",
                    "active_jobs": 1,
                    "last_seen": now_ts - 1,
                }
            ],
            working_workers=[
                {
                    "worker_id": "worker-chat-1",
                    "worker_pool": "chat",
                    "target_id": "ollama-main",
                    "target_kind": "cpu",
                    "active_jobs": 1,
                    "last_seen": now_ts - 1,
                }
            ],
            active_targets=[
                {
                    "target_id": "ollama-main",
                    "target_kind": "cpu",
                    "supports_workloads": ["chat", "parse"],
                    "base_capacity_tokens": 24,
                    "cpu_percent": 34.5,
                    "ram_free_mb": 8192,
                    "vram_free_mb": 0,
                    "loaded_models": ["phi3:mini"],
                    "last_seen": now_ts - 1,
                }
            ],
            runtime_state={
                "pending": {"chat:p1": 3, "parse:p2": 2, "siem:p3": 1},
                "active_jobs": 2,
                "targets": 1,
                "workers": 1,
            },
            metrics={
                "queue_depth": 6,
                "active_jobs": 2,
                "failed_jobs": 4,
                "rejected_jobs": 1,
                "job_latency_total_ms": 3600,
                "job_latency_count": 6,
            },
            capacity=True,
        )
        request = build_request(gateway)

        with patch.object(app_module.time, "time", return_value=now_ts):
            response = await app_module.get_admin_dashboard_summary(
                request,
                current_user={"username": "aitest"},
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["overall_status"], "ready")
        self.assertEqual(payload["readiness_status"], "ready")
        self.assertEqual(payload["queue_depth"], 6)
        self.assertEqual(payload["active_jobs"], 2)
        self.assertEqual(payload["workers_total"], 1)
        self.assertEqual(payload["workers_working"], 1)
        self.assertEqual(payload["targets"], 1)
        self.assertEqual(payload["failures"], 4)
        self.assertEqual(payload["rejected"], 1)
        self.assertEqual(payload["avg_latency_ms"], 600.0)
        self.assertEqual(payload["chat_backlog"], 3)
        self.assertEqual(payload["parser_backlog"], 2)
        self.assertEqual(payload["by_workload"]["chat"]["by_priority"]["p1"], 3)
        self.assertEqual(payload["active_models"], ["phi3:mini"])
        self.assertEqual(payload["worker_rows"][0]["status"], "working")
        self.assertEqual(payload["target_rows"][0]["target_id"], "ollama-main")
        self.assertEqual(payload["capacity_scope"], app_module.WORKLOAD_CHAT)
        self.assertEqual(payload["current_user"], "aitest")

    async def test_summary_endpoint_reports_degraded_state_when_capacity_is_unavailable(self):
        now_ts = 1_800_000_123
        gateway = FakeDashboardGateway(
            scheduler_status={"last_seen": now_ts - 3},
            active_workers=[
                {
                    "worker_id": "worker-chat-1",
                    "worker_pool": "chat",
                    "target_id": "ollama-main",
                    "target_kind": "cpu",
                    "active_jobs": 0,
                    "last_seen": now_ts - 2,
                }
            ],
            working_workers=[],
            active_targets=[
                {
                    "target_id": "ollama-main",
                    "target_kind": "cpu",
                    "supports_workloads": ["chat"],
                    "base_capacity_tokens": 8,
                    "cpu_percent": 78.0,
                    "ram_free_mb": 1024,
                    "vram_free_mb": 0,
                    "loaded_models": [],
                    "last_seen": now_ts - 2,
                }
            ],
            runtime_state={"pending": {"chat:p1": 1}, "active_jobs": 0, "targets": 1, "workers": 1},
            metrics={
                "queue_depth": 1,
                "active_jobs": 0,
                "failed_jobs": 0,
                "rejected_jobs": 0,
                "job_latency_total_ms": 0,
                "job_latency_count": 0,
            },
            capacity=False,
        )
        request = build_request(gateway)

        with patch.object(app_module.time, "time", return_value=now_ts):
            response = await app_module.get_admin_dashboard_summary(
                request,
                current_user={"username": "aitest"},
            )

        payload = json.loads(response.body)
        self.assertEqual(payload["overall_status"], "degraded")
        self.assertEqual(payload["readiness_status"], "not_ready")
        self.assertIsNone(payload["avg_latency_ms"])
        self.assertEqual(payload["active_models"], [])
        self.assertIn("Свободная chat capacity недоступна", payload["warnings"])


if __name__ == "__main__":
    unittest.main()

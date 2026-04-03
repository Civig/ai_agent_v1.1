import json
import os
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class FakeDashboardGateway:
    def __init__(
        self,
        *,
        scheduler_status=None,
        active_workers=None,
        working_workers=None,
        active_targets=None,
        runtime_state=None,
        metrics=None,
        capacity=True,
        redis_ok=True,
    ):
        self.scheduler_status = scheduler_status
        self.active_workers = list(active_workers or [])
        self.working_workers = list(working_workers or [])
        self.active_targets = list(active_targets or [])
        self.runtime_state = dict(runtime_state or {"pending": {}, "active_jobs": 0, "targets": 0, "workers": 0})
        self.metrics = dict(metrics or {"queue_depth": 0, "active_jobs": 0, "failed_jobs": 0, "rejected_jobs": 0, "job_latency_total_ms": 0, "job_latency_count": 0})
        self.capacity = capacity
        self.redis_ok = redis_ok
        self.redis = SimpleNamespace(ping=self._ping)

    async def _ping(self):
        return self.redis_ok

    async def get_scheduler_status(self):
        return self.scheduler_status

    async def list_active_workers(self):
        return list(self.active_workers)

    async def list_working_workers(self, workload_class=None):
        del workload_class
        return list(self.working_workers)

    async def can_accept_workload(self, workload_class=None):
        del workload_class
        return self.capacity

    async def get_runtime_state(self):
        return dict(self.runtime_state)

    async def get_basic_metrics(self):
        return dict(self.metrics)

    async def list_active_targets(self):
        return list(self.active_targets)


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


class AdminDashboardApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_endpoint_returns_real_runtime_shape(self):
        gateway = FakeDashboardGateway(
            scheduler_status={"last_seen": 1_900_000_000},
            active_workers=[
                {
                    "worker_id": "worker-a",
                    "worker_pool": "chat",
                    "target_id": "target-a",
                    "target_kind": "cpu",
                    "runtime_label": "ollama",
                    "node_id": "node-a",
                    "active_jobs": 1,
                    "supports_workloads": ["chat"],
                    "last_seen": 1_900_000_000,
                },
                {
                    "worker_id": "worker-b",
                    "worker_pool": "parser",
                    "target_id": "target-b",
                    "target_kind": "cpu",
                    "runtime_label": "parser",
                    "node_id": "node-b",
                    "active_jobs": 0,
                    "supports_workloads": ["parse"],
                    "last_seen": 1_900_000_000,
                },
            ],
            working_workers=[
                {
                    "worker_id": "worker-a",
                    "worker_pool": "chat",
                    "target_id": "target-a",
                }
            ],
            active_targets=[
                {
                    "target_id": "target-a",
                    "target_kind": "cpu",
                    "runtime_label": "ollama",
                    "supports_workloads": ["chat"],
                    "base_capacity_tokens": 8,
                    "loaded_models": ["phi3:mini", "gemma2:2b"],
                    "cpu_percent": 38.5,
                    "ram_free_mb": 8192,
                    "vram_free_mb": 0,
                    "gpu_utilization": 0,
                    "last_seen": 1_900_000_000,
                }
            ],
            runtime_state={
                "pending": {"chat:p1": 3, "chat:p2": 1, "parse:p2": 4},
                "active_jobs": 2,
                "targets": 1,
                "workers": 2,
            },
            metrics={
                "queue_depth": 8,
                "active_jobs": 2,
                "failed_jobs": 5,
                "rejected_jobs": 1,
                "job_latency_total_ms": 400,
                "job_latency_count": 2,
            },
            capacity=True,
            redis_ok=True,
        )
        request = build_request(gateway)

        response = await app_module.get_admin_dashboard_summary(
            request,
            current_user={"username": "aitest"},
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["overall_status"], "ready")
        self.assertEqual(payload["summary"]["queue_depth"], 8)
        self.assertEqual(payload["summary"]["active_jobs"], 2)
        self.assertEqual(payload["summary"]["workers_total"], 2)
        self.assertEqual(payload["summary"]["workers_working"], 1)
        self.assertEqual(payload["summary"]["targets"], 1)
        self.assertEqual(payload["summary"]["failed_jobs"], 5)
        self.assertEqual(payload["summary"]["rejected_jobs"], 1)
        self.assertEqual(payload["queues"]["chat_backlog"], 4)
        self.assertEqual(payload["queues"]["parser_backlog"], 4)
        self.assertEqual(payload["metrics"]["avg_latency_ms"], 200.0)
        self.assertEqual(payload["metrics"]["active_models"], ["gemma2:2b", "phi3:mini"])
        self.assertEqual(payload["workers"][0]["worker_id"], "worker-a")
        self.assertEqual(payload["workers"][0]["status"], "working")
        self.assertEqual(payload["targets"][0]["target_id"], "target-a")
        self.assertIn("last_refresh", payload)

    async def test_summary_endpoint_keeps_optional_metrics_unavailable_when_not_reported(self):
        gateway = FakeDashboardGateway(
            scheduler_status=None,
            active_workers=[],
            working_workers=[],
            active_targets=[],
            runtime_state={"pending": {"chat:p1": 0}, "active_jobs": 0, "targets": 0, "workers": 0},
            metrics={
                "queue_depth": 0,
                "active_jobs": 0,
                "failed_jobs": 0,
                "rejected_jobs": 0,
                "job_latency_total_ms": 0,
                "job_latency_count": 0,
            },
            capacity=False,
            redis_ok=False,
        )
        request = build_request(gateway)

        response = await app_module.get_admin_dashboard_summary(
            request,
            current_user={"username": "aitest"},
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["overall_status"], "not_ready")
        self.assertIsNone(payload["metrics"]["avg_latency_ms"])
        self.assertEqual(payload["metrics"]["active_models"], [])
        self.assertEqual(payload["workers"], [])
        self.assertEqual(payload["targets"], [])


if __name__ == "__main__":
    unittest.main()

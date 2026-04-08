import json
import os
import unittest
from fastapi import FastAPI
from starlette.requests import Request
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class FakeTelemetryGateway:
    def __init__(self):
        self.live = {
            "captured_at": 1_700_000_000,
            "captured_at_iso": "2025-01-01T00:00:00Z",
            "cpu_percent": 55.5,
            "queue_depth": 2,
        }
        self.history = [
            {
                "captured_at": 1_700_000_000,
                "captured_at_iso": "2025-01-01T00:00:00Z",
                "cpu_percent": 55.5,
                "queue_depth": 2,
            },
            {
                "captured_at": 1_700_000_300,
                "captured_at_iso": "2025-01-01T00:05:00Z",
                "cpu_percent": 35.5,
                "queue_depth": 1,
            },
        ]
        self.events = [
            {
                "timestamp": 1_700_000_300,
                "timestamp_iso": "2025-01-01T00:05:00Z",
                "severity": "warn",
                "source": "queue",
                "message": "Queue depth crossed warning threshold",
                "context": {"queue_depth": 11},
            }
        ]

    async def get_dashboard_live_sample(self):
        return dict(self.live)

    async def get_dashboard_history_samples(self, *, since_ts=None):
        return [item for item in self.history if item["captured_at"] >= int(since_ts or 0)]

    async def get_dashboard_events(self, *, limit=50):
        return list(self.events)[:limit]


def build_request(path: str, query_string: bytes = b"") -> Request:
    app = FastAPI()
    app.state.llm_gateway = FakeTelemetryGateway()
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": query_string,
            "app": app,
        }
    )


class AdminDashboardTelemetryAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_live_endpoint_returns_latest_sample(self):
        request = build_request("/api/admin/dashboard/live")
        response = await app_module.get_admin_dashboard_live(request, current_user={"username": "aitest"})
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["cpu_percent"], 55.5)
        self.assertEqual(payload["current_user"], "aitest")

    async def test_history_endpoint_returns_bucketed_points(self):
        request = build_request("/api/admin/dashboard/history", b"range=24h")
        with patch.object(app_module.time, "time", return_value=1_700_000_300):
            response = await app_module.get_admin_dashboard_history(
                request,
                range="24h",
                current_user={"username": "aitest"},
            )
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["range"], "24h")
        self.assertGreaterEqual(payload["point_count"], 1)
        self.assertEqual(payload["current_user"], "aitest")

    async def test_events_endpoint_returns_capped_log(self):
        request = build_request("/api/admin/dashboard/events", b"limit=10")
        response = await app_module.get_admin_dashboard_events(
            request,
            limit=10,
            current_user={"username": "aitest"},
        )
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["severity"], "warn")
        self.assertEqual(payload["current_user"], "aitest")


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

from dashboard_telemetry import (
    build_dashboard_events,
    build_dashboard_history_payload,
    build_dashboard_live_sample,
)


class DashboardTelemetryLogicTests(unittest.TestCase):
    def test_build_live_sample_reports_real_metrics_and_network_warmup_then_rate(self):
        summary = {
            "queue_depth": 3,
            "chat_backlog": 2,
            "parser_backlog": 1,
            "active_jobs": 2,
            "workers_total": 2,
            "workers_working": 1,
            "targets": 1,
            "capacity": True,
            "overall_status": "ready",
            "readiness_status": "ready",
            "health_status": "ok",
            "scheduler_status": "healthy",
            "active_models": ["demo"],
            "warnings": [],
            "target_rows": [
                {
                    "target_id": "ollama-main",
                    "status": "online",
                    "target_kind": "gpu",
                    "cpu_percent": 42.5,
                    "ram_total_mb": 16384,
                    "ram_free_mb": 8192,
                    "vram_total_mb": 12288,
                    "vram_free_mb": 4096,
                    "gpu_utilization": 67.0,
                    "gpu_temperature_c": 71.0,
                    "network_rx_bytes": 1_000,
                    "network_tx_bytes": 2_000,
                }
            ],
        }

        first = build_dashboard_live_sample(summary, now_ts=1_000)
        self.assertEqual(first["cpu_availability"], "reported")
        self.assertEqual(first["ram_used_mb"], 8192)
        self.assertEqual(first["gpu_availability"], "reported")
        self.assertEqual(first["network_availability"], "warming_up")
        self.assertIsNone(first["network_rx_bytes_per_sec"])

        summary["target_rows"][0]["network_rx_bytes"] = 2_500
        summary["target_rows"][0]["network_tx_bytes"] = 5_000
        second = build_dashboard_live_sample(summary, previous_sample=first, now_ts=1_005)
        self.assertEqual(second["network_availability"], "reported")
        self.assertEqual(second["network_rx_bytes_per_sec"], 300.0)
        self.assertEqual(second["network_tx_bytes_per_sec"], 600.0)

    def test_build_dashboard_events_emits_threshold_and_transition_events(self):
        previous = {
            "captured_at": 1_000,
            "readiness_status": "ready",
            "scheduler_status": "healthy",
            "queue_depth": 2,
            "chat_backlog": 1,
            "parser_backlog": 1,
            "capacity": True,
            "workers_total": 1,
            "gpu_availability": "reported",
        }
        current = {
            "captured_at": 1_030,
            "readiness_status": "not_ready",
            "scheduler_status": "stale",
            "queue_depth": 12,
            "chat_backlog": 6,
            "parser_backlog": 5,
            "capacity": False,
            "workers_total": 2,
            "gpu_availability": "unavailable",
        }

        events = build_dashboard_events(previous, current)
        messages = [event["message"] for event in events]
        self.assertIn("Readiness changed to not_ready", messages)
        self.assertIn("Scheduler heartbeat became unavailable", messages)
        self.assertIn("Queue depth crossed warning threshold", messages)
        self.assertIn("Chat backlog spike detected", messages)
        self.assertIn("Parser backlog spike detected", messages)
        self.assertIn("Chat capacity is unavailable", messages)
        self.assertIn("Worker count changed", messages)
        self.assertIn("GPU telemetry unavailable", messages)

    def test_history_payload_returns_bucketed_real_samples(self):
        samples = [
            {"captured_at": 1_000, "captured_at_iso": "a", "cpu_percent": 10.0},
            {"captured_at": 1_010, "captured_at_iso": "b", "cpu_percent": 20.0},
            {"captured_at": 1_020, "captured_at_iso": "c", "cpu_percent": 30.0},
            {"captured_at": 1_040, "captured_at_iso": "d", "cpu_percent": 40.0},
        ]

        with patch("dashboard_telemetry.time.time", return_value=1_050):
            payload = build_dashboard_history_payload(samples, range_key="1h", now_ts=1_050)

        self.assertEqual(payload["range"], "1h")
        self.assertEqual(payload["bucket_seconds"], 15)
        self.assertEqual(payload["point_count"], 4)
        self.assertEqual([point["captured_at_iso"] for point in payload["points"]], ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()

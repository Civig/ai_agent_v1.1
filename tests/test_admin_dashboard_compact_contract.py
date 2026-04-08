import json
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = REPO_ROOT / "static" / "js" / "admin-dashboard.js"


def evaluate_dashboard_compact_contract(script_body: str) -> dict:
    script = textwrap.dedent(
        f"""
        import fs from "fs";

        const source = fs.readFileSync({json.dumps(str(JS_PATH))}, "utf8");
        const sanitized = source
          .replace(/^import\\s+[^\\n]+\\n/gm, "")
          .replace(/if \\(typeof document !== "undefined"\\) \\{{[\\s\\S]*$/, "");
        const mod = await import(`data:text/javascript;base64,${{Buffer.from(sanitized).toString("base64")}}`);

        {script_body}
        """
    )

    completed = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


class AdminDashboardCompactContractTests(unittest.TestCase):
    def test_compact_top_level_contract_uses_short_cards_and_no_fake_latency(self):
        result = evaluate_dashboard_compact_contract(
            """
            const summary = {
              overall_status: "ready",
              readiness_status: "ready",
              health_status: "ok",
              redis: true,
              scheduler_status: "healthy",
              scheduler_age_seconds: 4,
              queue_depth: 0,
              active_jobs: 0,
              workers_total: 2,
              workers_working: 1,
              targets: 1,
              capacity: true,
              chat_backlog: 0,
              parser_backlog: 0,
              avg_latency_ms: 0,
              active_models: ["demo"],
            };

            console.log(JSON.stringify({
              latency: mod.formatLatency(summary.avg_latency_ms),
              summaryLabels: mod.buildOperationalSummary(summary).map((item) => item.label),
              kpiLabels: mod.buildKpiCards(summary).map((item) => item.label),
            }));
            """
        )

        self.assertEqual(result["latency"], "Нет данных")
        self.assertEqual(
            result["summaryLabels"],
            ["Что ограничивает систему сейчас", "Следующий chat-запрос", "Масштабирование"],
        )
        self.assertEqual(
            result["kpiLabels"],
            ["Состояние", "Запас", "Очередь", "Активные задачи", "Воркеры", "Цели", "Среднее время"],
        )

    def test_worker_snapshot_note_honestly_explains_aggregate_lag(self):
        result = evaluate_dashboard_compact_contract(
            """
            const summary = {
              active_jobs: 1,
              workers_working: 1,
            };
            const workers = [
              {
                worker_id: "worker-chat",
                status: "idle",
                active_jobs: 0,
              },
            ];

            console.log(JSON.stringify({
              note: mod.deriveWorkerSnapshotNote(summary, workers),
            }));
            """
        )

        self.assertIn("heartbeat snapshot", result["note"].lower())
        self.assertIn("отставать", result["note"])

    def test_target_workload_presentation_separates_reported_and_observed_usage(self):
        result = evaluate_dashboard_compact_contract(
            """
            const summary = {
              worker_rows: [
                {
                  worker_id: "worker-chat",
                  target_id: "ollama-main",
                  pool: "chat",
                  status: "working",
                },
              ],
            };
            const target = {
              target_id: "ollama-main",
              supports_workloads: ["batch"],
            };

            console.log(JSON.stringify(mod.buildTargetWorkloadPresentation(summary, target)));
            """
        )

        self.assertEqual(result["reported"], ["batch"])
        self.assertEqual(result["observed"], ["chat"])
        self.assertIn("Capabilities показаны отдельно", result["note"])

    def test_resource_cards_use_real_summary_fields_and_honest_no_data_placeholders(self):
        result = evaluate_dashboard_compact_contract(
            """
            const live = {
              cpu_percent: 60,
              cpu_availability: "reported",
              ram_total_mb: 12288,
              ram_free_mb: 6144,
              ram_used_mb: 6144,
              ram_availability: "reported",
              gpu_availability: "reported",
              gpu_utilization_percent: 73,
              gpu_temperature_c: 68,
              vram_free_mb: 4096,
              network_availability: "reported",
              network_rx_bytes_per_sec: 2048,
              network_tx_bytes_per_sec: 4096,
              queue_depth: 2,
              chat_backlog: 1,
              parser_backlog: 1,
              active_models: ["llama3", "qwen2.5"],
              sampling_interval_seconds: 5,
              telemetry_scope: "target heartbeat runtime telemetry",
            };
            const summary = { capacity: true, queue_depth: 2, chat_backlog: 1, parser_backlog: 1 };

            const cards = mod.buildResourceTelemetryCards(live, summary);
            console.log(JSON.stringify({
              cpu: cards.find((item) => item.key === "cpu"),
              network: cards.find((item) => item.key === "network"),
              queue: cards.find((item) => item.key === "queue"),
              models: cards.find((item) => item.key === "models"),
            }));
            """
        )

        self.assertEqual(result["cpu"]["value"], "60.0%")
        self.assertEqual(result["cpu"]["state"], "reported")
        self.assertIn("KB/s", result["network"]["value"])
        self.assertEqual(result["network"]["state"], "reported")
        self.assertEqual(result["queue"]["value"], "2")
        self.assertIn("chat backlog: 1", result["queue"]["detail"])
        self.assertEqual(result["models"]["value"], "2")
        self.assertIn("llama3", result["models"]["detail"])

    def test_history_and_event_views_stay_honest_when_backend_not_connected(self):
        result = evaluate_dashboard_compact_contract(
            """
            const history = mod.buildHistoryViewModel({}, "6h");
            const events = mod.buildEventLogViewModel({ events: [] });
            console.log(JSON.stringify({ history, events }));
            """
        )

        self.assertEqual(result["history"]["rangeLabel"], "6 часов")
        self.assertIn("нет данных", result["history"]["title"].lower())
        self.assertIn("нет сохранённых", result["history"]["note"].lower())
        self.assertIn("telemetry sampler", result["events"]["detail"].lower())
        self.assertIn("честно пустым", result["events"]["meta"].lower())


if __name__ == "__main__":
    unittest.main()

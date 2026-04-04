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


if __name__ == "__main__":
    unittest.main()

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = REPO_ROOT / "static" / "js" / "admin-dashboard.js"


def evaluate_dashboard_interpretation(summary: dict) -> dict:
    script = textwrap.dedent(
        f"""
        import fs from "fs";

        const source = fs.readFileSync({json.dumps(str(JS_PATH))}, "utf8");
        const sanitized = source
          .replace(/^import\\s+[^\\n]+\\n/gm, "")
          .replace(/if \\(typeof document !== "undefined"\\) \\{{[\\s\\S]*$/, "");
        const mod = await import(`data:text/javascript;base64,${{Buffer.from(sanitized).toString("base64")}}`);
        const summary = {json.dumps(summary, ensure_ascii=False)};

        console.log(JSON.stringify({{
          overall: mod.deriveOverallState(summary),
          capacity: mod.deriveCapacityAssessment(summary),
          bottleneck: mod.derivePrimaryBottleneck(summary),
          scaling: mod.deriveScalingHint(summary),
          queuePressure: mod.deriveQueuePressure(summary),
        }}));
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


class AdminDashboardOperatorInterpretationTests(unittest.TestCase):
    def test_healthy_capacity_scenario_is_reported_as_normal(self):
        result = evaluate_dashboard_interpretation(
            {
                "overall_status": "ready",
                "readiness_status": "ready",
                "health_status": "ok",
                "redis": True,
                "scheduler_status": "healthy",
                "scheduler_age_seconds": 3,
                "queue_depth": 0,
                "active_jobs": 0,
                "workers_total": 2,
                "workers_working": 1,
                "targets": 1,
                "capacity": True,
                "chat_backlog": 0,
                "parser_backlog": 0,
                "active_models": ["demo"],
            }
        )

        self.assertEqual(result["overall"]["title"], "Система работает штатно")
        self.assertEqual(result["capacity"]["state"], "Запас есть")
        self.assertEqual(result["bottleneck"]["title"], "Явных ограничений не видно")
        self.assertIn("может принимать новые chat-запросы", result["scaling"]["title"])
        self.assertEqual(result["queuePressure"]["state"], "Нет давления")

    def test_busy_single_active_job_without_queue_is_reported_as_limited_capacity(self):
        result = evaluate_dashboard_interpretation(
            {
                "overall_status": "degraded",
                "readiness_status": "not_ready",
                "health_status": "ok",
                "redis": True,
                "scheduler_status": "healthy",
                "scheduler_age_seconds": 5,
                "queue_depth": 0,
                "active_jobs": 1,
                "workers_total": 1,
                "workers_working": 1,
                "targets": 1,
                "capacity": False,
                "chat_backlog": 0,
                "parser_backlog": 0,
                "active_models": ["demo"],
            }
        )

        self.assertEqual(result["overall"]["title"], "Система занята, но работает")
        self.assertEqual(result["capacity"]["state"], "Запас ограничен")
        self.assertIn("следующий chat-запрос может ждать", result["capacity"]["reason"])
        self.assertEqual(result["queuePressure"]["state"], "Система занята")
        self.assertIn("Очередь пустая, потому что задача уже выполняется", result["queuePressure"]["detail"])
        self.assertIn("Следующий chat-запрос вероятно будет ждать", result["scaling"]["title"])

    def test_chat_backlog_without_capacity_is_reported_as_real_pressure(self):
        result = evaluate_dashboard_interpretation(
            {
                "overall_status": "degraded",
                "readiness_status": "not_ready",
                "health_status": "ok",
                "redis": True,
                "scheduler_status": "healthy",
                "scheduler_age_seconds": 7,
                "queue_depth": 3,
                "active_jobs": 1,
                "workers_total": 1,
                "workers_working": 1,
                "targets": 1,
                "capacity": False,
                "chat_backlog": 3,
                "parser_backlog": 0,
                "active_models": ["demo"],
            }
        )

        self.assertEqual(result["overall"]["title"], "Новые chat-задачи будут ждать")
        self.assertEqual(result["capacity"]["state"], "Запас исчерпан")
        self.assertEqual(result["bottleneck"]["title"], "Свободная chat capacity уже занята")
        self.assertIn("дополнительная вычислительная цель", result["scaling"]["title"])
        self.assertEqual(result["queuePressure"]["state"], "Высокое давление")

    def test_stale_scheduler_is_reported_as_insufficient_signal(self):
        result = evaluate_dashboard_interpretation(
            {
                "overall_status": "degraded",
                "readiness_status": "not_ready",
                "health_status": "degraded",
                "redis": True,
                "scheduler_status": "stale",
                "scheduler_age_seconds": 95,
                "queue_depth": 0,
                "active_jobs": 0,
                "workers_total": 1,
                "workers_working": 1,
                "targets": 1,
                "capacity": False,
                "chat_backlog": 0,
                "parser_backlog": 0,
                "active_models": ["demo"],
            }
        )

        self.assertEqual(result["overall"]["title"], "Данных недостаточно для точной оценки")
        self.assertEqual(result["capacity"]["state"], "Оценка запаса недоступна")
        self.assertEqual(result["bottleneck"]["title"], "Планировщик публикует устаревший heartbeat")
        self.assertEqual(result["scaling"]["title"], "Недостаточно данных для точной оценки запаса")


if __name__ == "__main__":
    unittest.main()

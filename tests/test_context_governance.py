import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
from app import build_document_prompt
from llm_gateway import MAX_HISTORY_CHARS, MAX_HISTORY_MESSAGES, MAX_TOTAL_PROMPT_CHARS, SYSTEM_PROMPT, apply_history_budget, prepare_ollama_messages


class ContextGovernanceTests(unittest.IsolatedAsyncioTestCase):
    def test_apply_history_budget_keeps_recent_messages_and_order(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
            {"role": "assistant", "content": "fourth"},
            {"role": "user", "content": "fifth"},
            {"role": "assistant", "content": "sixth"},
        ]

        limited = apply_history_budget(history)

        self.assertEqual(len(limited), MAX_HISTORY_MESSAGES)
        self.assertEqual([message["content"] for message in limited], ["second", "third", "fourth", "fifth", "sixth"])

    def test_apply_history_budget_trims_long_history_without_crashing(self):
        history = [
            {"role": "user", "content": "A" * (MAX_HISTORY_CHARS // 2)},
            {"role": "assistant", "content": "B" * (MAX_HISTORY_CHARS // 2)},
            {"role": "user", "content": "C" * (MAX_HISTORY_CHARS // 2)},
        ]

        limited = apply_history_budget(history)

        self.assertGreaterEqual(len(limited), 1)
        self.assertLessEqual(sum(len(message["content"]) for message in limited), MAX_HISTORY_CHARS)
        self.assertEqual([message["content"][0] for message in limited], ["B", "C"])

    async def test_api_chat_enqueues_budgeted_history(self):
        long_history = [{"role": "user", "content": "X" * (MAX_HISTORY_CHARS + 500)}]
        expected_history = apply_history_budget(long_history)
        request = object()
        current_user = {"username": "alice"}

        gateway = type("Gateway", (), {})()
        gateway.get_queue_pressure = AsyncMock(return_value={"queue_depth": 0, "threshold": 10})
        gateway.get_model_catalog = AsyncMock(return_value={"demo": {"name": "demo"}})
        gateway.enqueue_job = AsyncMock(return_value="job-1")

        chat_store = type("ChatStore", (), {})()
        chat_store.get_history = AsyncMock(return_value=long_history)
        chat_store.append_message = AsyncMock(return_value=None)

        app_state = type("State", (), {"llm_gateway": gateway, "chat_store": chat_store, "rate_limiter": type("Limiter", (), {"check": AsyncMock(return_value=None)})()})()

        with unittest.mock.patch.object(app_module, "enforce_csrf", return_value=None), unittest.mock.patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ):
            fake_request = type(
                "Req",
                (),
                {
                    "app": type("App", (), {"state": app_state})(),
                    "json": AsyncMock(return_value={"prompt": "hello"}),
                },
            )()
            response = await app_module.api_chat(fake_request, current_user=current_user)

        self.assertEqual(response.status_code, 200)
        gateway.enqueue_job.assert_awaited_once()
        self.assertEqual(gateway.enqueue_job.await_args.kwargs["history"], expected_history)
        self.assertEqual(gateway.enqueue_job.await_args.kwargs["thread_id"], app_module.DEFAULT_CHAT_THREAD_ID)
        self.assertEqual(chat_store.get_history.await_args.kwargs["thread_id"], app_module.DEFAULT_CHAT_THREAD_ID)
        self.assertEqual(chat_store.append_message.await_args.kwargs["thread_id"], app_module.DEFAULT_CHAT_THREAD_ID)

    def test_prepare_ollama_messages_trims_history_before_user_prompt(self):
        history = [
            {"role": "user", "content": "A" * (MAX_HISTORY_CHARS // 2)},
            {"role": "assistant", "content": "B" * (MAX_HISTORY_CHARS // 2)},
            {"role": "user", "content": "C" * (MAX_HISTORY_CHARS // 2)},
        ]
        prompt = "Короткий пользовательский запрос"

        messages = prepare_ollama_messages(history, prompt)

        self.assertEqual(messages[0]["content"], SYSTEM_PROMPT)
        self.assertEqual(messages[-1]["content"], prompt)
        self.assertLess(sum(len(message["content"]) for message in messages), MAX_TOTAL_PROMPT_CHARS + 1)
        self.assertEqual([message["content"][0] for message in messages[1:-1]], ["B", "C"])

    def test_prepare_ollama_messages_preserves_document_labels_and_request(self):
        prompt = build_document_prompt(
            "Какая сумма указана?",
            [
                {"name": "big.txt", "content": "A" * (MAX_TOTAL_PROMPT_CHARS * 2)},
                {"name": "second.txt", "content": "B" * 500},
            ],
        )

        messages = prepare_ollama_messages([], prompt)
        final_prompt = messages[-1]["content"]

        self.assertIn("# ДОКУМЕНТЫ", final_prompt)
        self.assertIn("[Документ 1: big.txt]", final_prompt)
        self.assertIn("# ЗАПРОС ПОЛЬЗОВАТЕЛЯ", final_prompt)
        self.assertIn("Какая сумма указана?", final_prompt)
        self.assertLessEqual(sum(len(message["content"]) for message in messages), MAX_TOTAL_PROMPT_CHARS)


if __name__ == "__main__":
    unittest.main()

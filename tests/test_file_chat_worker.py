import json
import os
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

fake_httpx = types.SimpleNamespace(
    AsyncClient=object,
    Timeout=lambda *args, **kwargs: None,
    Limits=lambda *args, **kwargs: None,
    ConnectError=RuntimeError,
    ReadTimeout=TimeoutError,
    RemoteProtocolError=RuntimeError,
    HTTPStatusError=RuntimeError,
    Response=object,
)
sys.modules.setdefault("httpx", fake_httpx)

from llm_gateway import JOB_KIND_FILE_CHAT
from worker import LLMWorker


class FakeStreamResponse:
    def __init__(self, lines):
        self._lines = list(lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aclose(self):
        return None


class FileChatWorkerTests(unittest.IsolatedAsyncioTestCase):
    def build_worker(self) -> LLMWorker:
        worker = LLMWorker()
        worker.gateway = type("Gateway", (), {})()
        worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
        worker.gateway.emit_event = AsyncMock(return_value=None)
        worker.gateway.mark_job_completed = AsyncMock(return_value=None)
        worker.gateway.mark_job_failed = AsyncMock(return_value=None)
        worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

        worker.chat_store = type("ChatStore", (), {})()
        worker.chat_store.append_message = AsyncMock(return_value=None)

        worker.ollama = type("Ollama", (), {})()
        return worker

    async def test_file_chat_job_retries_and_completes_with_final_result(self):
        worker = self.build_worker()
        worker.ollama.stream_chat = AsyncMock(
            side_effect=[
                FakeStreamResponse(
                    [
                        json.dumps({"message": {"content": "Я не имею доступа к файлам"}}),
                        json.dumps({"done": True}),
                    ]
                ),
                FakeStreamResponse(
                    [
                        json.dumps({"message": {"content": "Сумма договора: 10 руб."}}),
                        json.dumps({"done": True}),
                    ]
                ),
            ]
        )

        job = {
            "id": "job-file",
            "username": "alice",
            "model_name": "demo",
            "prompt": "initial prompt",
            "history": [],
            "deadline_at": int(time.time()) + 30,
            "job_kind": JOB_KIND_FILE_CHAT,
            "file_chat": {
                "retry_prompt": "retry prompt",
                "suppress_token_stream": True,
                "doc_chars": 123,
                "files": [{"name": "report.txt", "size": 12}],
            },
        }

        with self.assertLogs("llm_worker", level="INFO") as captured:
            await worker.process_job(job)

        worker.gateway.mark_job_completed.assert_awaited_once()
        self.assertEqual(worker.gateway.mark_job_completed.await_args.args[1], "Сумма договора: 10 руб.")
        worker.gateway.emit_event.assert_any_await("job-file", {"result": "Сумма договора: 10 руб."})
        token_events = [call for call in worker.gateway.emit_event.await_args_list if call.args[1].get("token")]
        self.assertEqual(token_events, [])
        joined_logs = "\n".join(captured.output)
        self.assertIn("job_terminal_observability", joined_logs)
        self.assertIn("file_count=1", joined_logs)
        self.assertIn("doc_chars=123", joined_logs)
        self.assertIn("inference_ms=", joined_logs)
        self.assertIn("total_ms=", joined_logs)

    async def test_normal_chat_job_still_streams_tokens(self):
        worker = self.build_worker()
        worker.ollama.stream_chat = AsyncMock(
            return_value=FakeStreamResponse(
                [
                    json.dumps({"message": {"content": "OK"}}),
                    json.dumps({"done": True}),
                ]
            )
        )

        job = {
            "id": "job-chat",
            "username": "alice",
            "model_name": "demo",
            "prompt": "hello",
            "history": [],
            "deadline_at": int(time.time()) + 30,
        }

        await worker.process_job(job)

        worker.gateway.emit_event.assert_any_await("job-chat", {"token": "OK"})
        worker.gateway.mark_job_completed.assert_awaited_once()

    async def test_file_chat_job_error_marks_terminal_failure(self):
        worker = self.build_worker()
        worker.ollama.stream_chat = AsyncMock(side_effect=RuntimeError("boom"))

        job = {
            "id": "job-file-error",
            "username": "alice",
            "model_name": "demo",
            "prompt": "initial prompt",
            "history": [],
            "deadline_at": int(time.time()) + 30,
            "job_kind": JOB_KIND_FILE_CHAT,
            "file_chat": {
                "retry_prompt": "retry prompt",
                "suppress_token_stream": True,
                "files": [{"name": "report.txt", "size": 12}],
            },
        }

        await worker.process_job(job)

        worker.gateway.mark_job_failed.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

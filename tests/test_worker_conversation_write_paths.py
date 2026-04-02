import os
import sys
import types
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

if "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class _Dummy:
        def __init__(self, *args, **kwargs):
            del args, kwargs

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def aclose(self) -> None:
            return None

    class _Response:
        def __init__(self, *args, status_code: int = 200, **kwargs):
            del args, kwargs
            self.status_code = status_code

        def raise_for_status(self) -> None:
            return None

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs):
            super().__init__(*args)
            self.response = response or types.SimpleNamespace(status_code=500)
            self.request = kwargs.get("request")

    fake_httpx.AsyncClient = _AsyncClient
    fake_httpx.Timeout = _Dummy
    fake_httpx.Limits = _Dummy
    fake_httpx.Response = _Response
    fake_httpx.ConnectError = type("ConnectError", (Exception,), {})
    fake_httpx.ReadTimeout = type("ReadTimeout", (Exception,), {})
    fake_httpx.RemoteProtocolError = type("RemoteProtocolError", (Exception,), {})
    fake_httpx.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = fake_httpx

import worker as worker_module


class FakeGateway:
    def __init__(self, *, cancel_requested: bool = False):
        self.cancel_requested = cancel_requested
        self.completed_calls: list[tuple[str, str, str]] = []
        self.cancelled_calls: list[tuple[str, str]] = []
        self.failed_calls: list[tuple[str, str, str]] = []

    async def is_cancel_requested(self, job_id: str) -> bool:
        del job_id
        return self.cancel_requested

    async def mark_job_completed(self, job_id: str, response_text: str, *, worker_id: str | None = None) -> None:
        self.completed_calls.append((job_id, response_text, worker_id or ""))

    async def mark_job_cancelled(self, job_id: str, *, worker_id: str | None = None) -> None:
        self.cancelled_calls.append((job_id, worker_id or ""))

    async def mark_job_failed(self, job_id: str, error_text: str, *, worker_id: str | None = None) -> None:
        self.failed_calls.append((job_id, error_text, worker_id or ""))


class FakeConversationWriter:
    def __init__(self):
        self.append_message_calls: list[tuple[str, str, str, str]] = []

    async def append_message(self, username: str, role: str, content: str, *, thread_id: str | None = None) -> None:
        self.append_message_calls.append((username, role, content, thread_id or ""))


class WorkerConversationWritePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_job_uses_coordinator_for_terminal_success_write(self):
        gateway = FakeGateway(cancel_requested=False)
        writer = FakeConversationWriter()
        worker = worker_module.LLMWorker.__new__(worker_module.LLMWorker)
        worker.gateway = gateway
        worker.conversation_writer = writer
        worker.worker_id = "worker-1"
        worker._run_generation = AsyncMock(return_value=("Готово", 12))
        worker._run_file_chat_job = AsyncMock()

        await worker_module.LLMWorker.process_job(
            worker,
            {
                "id": "job-1",
                "username": "alice",
                "thread_id": "thread-1",
                "model_name": "demo",
                "prompt": "Привет",
                "history": [],
            },
        )

        self.assertEqual(
            writer.append_message_calls,
            [("alice", "assistant", "Готово", "thread-1")],
        )
        self.assertEqual(gateway.completed_calls, [("job-1", "Готово", "worker-1")])

    async def test_process_job_uses_coordinator_for_terminal_cancel_write(self):
        gateway = FakeGateway(cancel_requested=True)
        writer = FakeConversationWriter()
        worker = worker_module.LLMWorker.__new__(worker_module.LLMWorker)
        worker.gateway = gateway
        worker.conversation_writer = writer
        worker.worker_id = "worker-1"
        worker._run_generation = AsyncMock()
        worker._run_file_chat_job = AsyncMock()

        await worker_module.LLMWorker.process_job(
            worker,
            {
                "id": "job-2",
                "username": "alice",
                "thread_id": "thread-2",
                "model_name": "demo",
                "prompt": "Привет",
                "history": [],
            },
        )

        self.assertEqual(
            writer.append_message_calls,
            [("alice", "assistant", worker_module.CANCELLED_TEXT, "thread-2")],
        )
        self.assertEqual(gateway.cancelled_calls, [("job-2", "worker-1")])


if __name__ == "__main__":
    unittest.main()

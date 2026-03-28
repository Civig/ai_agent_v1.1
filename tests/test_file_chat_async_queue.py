import io
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
from fastapi.responses import StreamingResponse

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module


class DummyTempDir:
    def __init__(self):
        self.cleaned = 0

    def cleanup(self):
        self.cleaned += 1


class DummyRateLimiter:
    async def check(self, subject):
        return None


async def fake_stream_events(job_id):
    yield {"queued": True}
    yield {"result": "ok"}
    yield {"done": True}


class FileChatAsyncQueueTests(unittest.IsolatedAsyncioTestCase):
    def build_request(self, gateway, chat_store, *, accept="application/json"):
        return type(
            "Req",
            (),
            {
                "headers": {"accept": accept},
                "app": type(
                    "App",
                    (),
                    {
                        "state": type(
                            "State",
                            (),
                            {
                                "llm_gateway": gateway,
                                "chat_store": chat_store,
                                "rate_limiter": DummyRateLimiter(),
                            },
                        )()
                    },
                )(),
            },
        )()

    def build_gateway(self):
        gateway = type("Gateway", (), {})()
        gateway.get_queue_pressure = AsyncMock(return_value={"queue_depth": 0, "threshold": 10})
        gateway.get_model_catalog = AsyncMock(return_value={"demo": {"name": "demo"}})
        gateway.stream_events = fake_stream_events
        gateway.cancel_job = AsyncMock(return_value=True)
        return gateway

    def build_chat_store(self):
        chat_store = type("ChatStore", (), {})()
        chat_store.get_history = AsyncMock(return_value=[])
        chat_store.append_message = AsyncMock(return_value=None)
        chat_store.clear_history = AsyncMock(return_value=None)
        return chat_store

    async def test_file_chat_sse_branch_enqueues_without_waiting(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store, accept="text/event-stream")
        temp_dir = DummyTempDir()

        with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads",
            AsyncMock(return_value=(temp_dir, [{"name": "note.txt", "size": 5}])),
        ), patch.object(
            app_module,
            "extract_documents_from_staging",
            return_value=[{"name": "note.txt", "content": "hello"}],
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(return_value="job-1"),
        ) as enqueue_mock, patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(side_effect=AssertionError("wait_for_terminal_job should not be called for SSE branch")),
        ):
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertIsInstance(response, StreamingResponse)
        enqueue_mock.assert_awaited_once()
        self.assertEqual(temp_dir.cleaned, 1)

    async def test_file_chat_json_fallback_returns_completed_payload(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)
        temp_dir = DummyTempDir()

        with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads",
            AsyncMock(return_value=(temp_dir, [{"name": "note.txt", "size": 5}])),
        ), patch.object(
            app_module,
            "extract_documents_from_staging",
            return_value=[{"name": "note.txt", "content": "hello"}],
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(return_value="job-1"),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "completed", "result": "done"}),
        ):
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"response":"done"', response.body)
        self.assertEqual(temp_dir.cleaned, 1)

    async def test_file_chat_json_fallback_returns_error_payload(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)
        temp_dir = DummyTempDir()

        with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads",
            AsyncMock(return_value=(temp_dir, [{"name": "note.txt", "size": 5}])),
        ), patch.object(
            app_module,
            "extract_documents_from_staging",
            return_value=[{"name": "note.txt", "content": "hello"}],
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(return_value="job-1"),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "failed", "error": "boom"}),
        ):
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"error":"boom"', response.body)


if __name__ == "__main__":
    unittest.main()

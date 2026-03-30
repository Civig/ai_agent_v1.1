import asyncio
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
    async def collect_stream_chunks(self, response):
        chunks = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8")
            chunks.append(chunk)
        return chunks

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

        with patch.object(app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", False), patch.object(
            app_module, "enforce_csrf", return_value=None
        ), patch.object(
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
            "enqueue_parser_job",
            AsyncMock(side_effect=AssertionError("enqueue_parser_job should not be called for legacy path")),
        ), patch.object(
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
        chunks = await self.collect_stream_chunks(response)
        enqueue_mock.assert_awaited_once()
        self.assertIn('"job_id": "job-1"', chunks[0])
        self.assertEqual(temp_dir.cleaned, 1)

    async def test_file_chat_json_fallback_returns_completed_payload(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)
        temp_dir = DummyTempDir()

        with patch.object(app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", False), patch.object(
            app_module, "enforce_csrf", return_value=None
        ), patch.object(
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
            "enqueue_parser_job",
            AsyncMock(side_effect=AssertionError("enqueue_parser_job should not be called for legacy path")),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "completed", "result": "done"}),
        ) as wait_mock:
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"response":"done"', response.body)
        self.assertIn(b'"job_id":"job-1"', response.body)
        wait_mock.assert_awaited_once_with(gateway, "job-1", app_module.settings.LLM_JOB_DEADLINE_SECONDS)
        self.assertEqual(temp_dir.cleaned, 1)

    async def test_file_chat_json_fallback_returns_error_payload(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)
        temp_dir = DummyTempDir()

        with patch.object(app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", False), patch.object(
            app_module, "enforce_csrf", return_value=None
        ), patch.object(
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
            "enqueue_parser_job",
            AsyncMock(side_effect=AssertionError("enqueue_parser_job should not be called for legacy path")),
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

    async def test_file_chat_sse_branch_uses_root_job_id_under_public_cutover_flag(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store, accept="text/event-stream")
        seen_stream_job_ids = []

        async def stream_events(job_id):
            seen_stream_job_ids.append(job_id)
            yield {"source_job_id": "child-1", "token": "hello"}
            yield {"source_job_id": "child-1", "done": True}

        gateway.stream_events = stream_events

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", True
        ), patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads_for_parser",
            AsyncMock(
                return_value={
                    "staging_id": "staging-1",
                    "files": [
                        {
                            "name": "note.txt",
                            "safe_name": "safe-note.txt",
                            "size": 5,
                            "content_type": "text/plain",
                        }
                    ],
                }
            ),
        ), patch.object(
            app_module,
            "enqueue_parser_job",
            AsyncMock(return_value="root-job-1"),
        ) as enqueue_parser_mock, patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(side_effect=AssertionError("enqueue_document_job should not be called for parser public cutover")),
        ):
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertIsInstance(response, StreamingResponse)
        chunks = await self.collect_stream_chunks(response)
        enqueue_parser_mock.assert_awaited_once()
        self.assertEqual(seen_stream_job_ids, ["root-job-1"])
        self.assertIn('"job_id": "root-job-1"', chunks[0])
        self.assertTrue(any('"source_job_id": "child-1"' in chunk for chunk in chunks[1:]))
        self.assertTrue(any('"done": true' in chunk for chunk in chunks[1:]))
        chat_store.append_message.assert_awaited_once()
        self.assertEqual(chat_store.append_message.await_args.args[:2], ("alice", "user"))
        self.assertIn("Summarize", chat_store.append_message.await_args.args[2])
        self.assertIn("note.txt", chat_store.append_message.await_args.args[2])

    async def test_file_chat_sse_cancel_uses_root_job_id_under_public_cutover_flag(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store, accept="text/event-stream")

        async def stream_events(job_id):
            yield {"source_job_id": "child-1", "token": "hello"}
            await asyncio.sleep(60)

        gateway.stream_events = stream_events

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", True
        ), patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads_for_parser",
            AsyncMock(
                return_value={
                    "staging_id": "staging-1",
                    "files": [
                        {
                            "name": "note.txt",
                            "safe_name": "safe-note.txt",
                            "size": 5,
                            "content_type": "text/plain",
                        }
                    ],
                }
            ),
        ), patch.object(
            app_module,
            "enqueue_parser_job",
            AsyncMock(return_value="root-job-1"),
        ):
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertIsInstance(response, StreamingResponse)
        first_chunk = await response.body_iterator.__anext__()
        if isinstance(first_chunk, bytes):
            first_chunk = first_chunk.decode("utf-8")
        self.assertIn('"job_id": "root-job-1"', first_chunk)
        with self.assertRaises(asyncio.CancelledError):
            await response.body_iterator.athrow(asyncio.CancelledError())
        gateway.cancel_job.assert_awaited_once_with("root-job-1", username="alice")

    async def test_file_chat_json_fallback_uses_root_job_id_under_public_cutover_flag(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", True
        ), patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads_for_parser",
            AsyncMock(
                return_value={
                    "staging_id": "staging-1",
                    "files": [
                        {
                            "name": "note.txt",
                            "safe_name": "safe-note.txt",
                            "size": 5,
                            "content_type": "text/plain",
                        }
                    ],
                }
            ),
        ), patch.object(
            app_module,
            "enqueue_parser_job",
            AsyncMock(return_value="root-job-1"),
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(side_effect=AssertionError("enqueue_document_job should not be called for parser public cutover")),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "completed", "result": "done"}),
        ) as wait_mock, patch.object(
            app_module,
            "response_requires_document_retry",
            side_effect=AssertionError("legacy app-side retry should not run for parser-root JSON path"),
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
        self.assertIn(b'"job_id":"root-job-1"', response.body)
        self.assertIn(b'"files":[{"name":"note.txt","size":5}]', response.body)
        wait_mock.assert_awaited_once_with(gateway, "root-job-1", app_module.parser_public_json_timeout_seconds())
        chat_store.append_message.assert_awaited_once()
        self.assertEqual(chat_store.append_message.await_args.args[:2], ("alice", "user"))

    async def test_file_chat_json_fallback_returns_failed_payload_under_public_cutover_flag(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", True
        ), patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads_for_parser",
            AsyncMock(
                return_value={
                    "staging_id": "staging-1",
                    "files": [
                        {
                            "name": "note.txt",
                            "safe_name": "safe-note.txt",
                            "size": 5,
                            "content_type": "text/plain",
                        }
                    ],
                }
            ),
        ), patch.object(
            app_module,
            "enqueue_parser_job",
            AsyncMock(return_value="root-job-1"),
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(side_effect=AssertionError("enqueue_document_job should not be called for parser public cutover")),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "failed", "error": "boom"}),
        ) as wait_mock, patch.object(
            app_module,
            "response_requires_document_retry",
            side_effect=AssertionError("legacy app-side retry should not run for parser-root JSON path"),
        ), patch.object(
            app_module,
            "restore_chat_history",
            AsyncMock(return_value=None),
        ) as restore_mock:
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'"error":"boom"', response.body)
        wait_mock.assert_awaited_once_with(gateway, "root-job-1", app_module.parser_public_json_timeout_seconds())
        restore_mock.assert_awaited_once()

    async def test_file_chat_json_fallback_returns_cancelled_payload_under_public_cutover_flag(self):
        gateway = self.build_gateway()
        chat_store = self.build_chat_store()
        request = self.build_request(gateway, chat_store)

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            app_module.settings, "ENABLE_PARSER_PUBLIC_CUTOVER", True
        ), patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ), patch.object(
            app_module,
            "stage_uploads_for_parser",
            AsyncMock(
                return_value={
                    "staging_id": "staging-1",
                    "files": [
                        {
                            "name": "note.txt",
                            "safe_name": "safe-note.txt",
                            "size": 5,
                            "content_type": "text/plain",
                        }
                    ],
                }
            ),
        ), patch.object(
            app_module,
            "enqueue_parser_job",
            AsyncMock(return_value="root-job-1"),
        ), patch.object(
            app_module,
            "enqueue_document_job",
            AsyncMock(side_effect=AssertionError("enqueue_document_job should not be called for parser public cutover")),
        ), patch.object(
            app_module,
            "wait_for_terminal_job",
            AsyncMock(return_value={"status": "cancelled"}),
        ) as wait_mock, patch.object(
            app_module,
            "restore_chat_history",
            AsyncMock(return_value=None),
        ) as restore_mock:
            response = await app_module.api_chat_with_files(
                request,
                message="Summarize",
                model=None,
                files=[UploadFile(filename="note.txt", file=io.BytesIO(b"hello"))],
                current_user={"username": "alice", "model_key": "demo", "model": "demo"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Генерация была отменена".encode("utf-8"), response.body)
        wait_mock.assert_awaited_once_with(gateway, "root-job-1", app_module.parser_public_json_timeout_seconds())
        restore_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

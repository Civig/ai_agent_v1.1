import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import app as app_module


class FakeChatStore:
    def __init__(self):
        self.threads: list[dict[str, object]] = []

    async def list_threads(self, username: str):
        del username
        return list(self.threads)

    async def get_history(self, username: str, *, thread_id: str | None = None):
        del username, thread_id
        return []


class FakeConversationWriter:
    def __init__(self, chat_store: FakeChatStore | None = None):
        self.chat_store = chat_store
        self.ensure_thread_calls: list[tuple[str, str | None]] = []
        self.append_message_calls: list[tuple[str, str, str, str | None]] = []
        self.clear_thread_calls: list[tuple[str, str | None, bool]] = []
        self.replace_snapshot_calls: list[tuple[str, str, list[dict[str, object]]]] = []

    async def ensure_thread(self, username: str, *, thread_id: str | None = None) -> str:
        self.ensure_thread_calls.append((username, thread_id))
        if self.chat_store is not None:
            normalized_thread_id = thread_id or "default"
            self.chat_store.threads.append(
                {
                    "thread_id": normalized_thread_id,
                    "updated_at": 0,
                    "title": "Новый чат",
                    "message_count": 0,
                }
            )
            return normalized_thread_id
        return thread_id or "default"

    async def append_message(
        self,
        username: str,
        role: str,
        content: str,
        *,
        thread_id: str | None = None,
    ) -> None:
        self.append_message_calls.append((username, role, content, thread_id))

    async def clear_thread(
        self,
        username: str,
        *,
        thread_id: str | None = None,
        preserve_thread: bool = True,
    ) -> None:
        self.clear_thread_calls.append((username, thread_id, preserve_thread))

    async def replace_thread_snapshot(
        self,
        username: str,
        thread_id: str,
        messages: list[dict[str, object]],
    ) -> None:
        self.replace_snapshot_calls.append((username, thread_id, list(messages)))


def build_request(*, path: str, query_string: bytes = b"") -> Request:
    app = FastAPI()
    app.state.chat_store = object()
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": query_string,
            "app": app,
        }
    )


class AppConversationWritePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_thread_summaries_uses_coordinator_for_default_bootstrap(self):
        chat_store = FakeChatStore()
        writer = FakeConversationWriter(chat_store)

        threads = await app_module.load_thread_summaries(
            chat_store,
            "alice",
            conversation_writer=writer,
        )

        self.assertEqual(writer.ensure_thread_calls, [("alice", "default")])
        self.assertEqual([thread["id"] for thread in threads], ["default"])

    async def test_enqueue_document_job_uses_coordinator_for_user_history_entry(self):
        writer = FakeConversationWriter()
        gateway = AsyncMock()
        gateway.enqueue_job.return_value = "job-1"

        job_id = await app_module.enqueue_document_job(
            gateway=gateway,
            conversation_writer=writer,
            username="alice",
            thread_id="default",
            model_info={"key": "demo", "name": "demo"},
            prompt="prompt",
            history=[],
            history_entry="user entry",
            file_chat=None,
        )

        self.assertEqual(job_id, "job-1")
        self.assertEqual(
            writer.append_message_calls,
            [("alice", "user", "user entry", "default")],
        )

    async def test_restore_chat_history_uses_replace_snapshot_semantics(self):
        writer = FakeConversationWriter()
        history = [{"role": "user", "content": "Привет"}]

        await app_module.restore_chat_history(writer, "alice", "default", history)

        self.assertEqual(writer.replace_snapshot_calls, [("alice", "default", history)])

    async def test_clear_chat_endpoint_uses_coordinator_clear_thread(self):
        writer = FakeConversationWriter()
        request = build_request(path="/api/chat/clear", query_string=b"thread_id=case-1")

        with (
            patch.object(app_module, "create_conversation_write_coordinator", return_value=writer),
            patch.object(app_module, "enforce_csrf"),
        ):
            response = await app_module.clear_chat(
                request,
                current_user={"username": "alice"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), {"ok": True, "thread_id": "case-1"})
        self.assertEqual(writer.clear_thread_calls, [("alice", "case-1", True)])


if __name__ == "__main__":
    unittest.main()

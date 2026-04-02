import json
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import app as app_module


class FakeChatStore:
    @staticmethod
    def build_thread_title(history):
        return app_module.AsyncChatStore.build_thread_title(history)


class FakeConversationDbStore:
    def __init__(self, *, threads=None, messages_by_thread=None, error: Exception | None = None):
        self.threads = list(threads or [])
        self.messages_by_thread = dict(messages_by_thread or {})
        self.error = error
        self.list_calls: list[str] = []
        self.message_calls: list[tuple[str, str]] = []

    def list_threads(self, username: str):
        self.list_calls.append(username)
        if self.error is not None:
            raise self.error
        return list(self.threads)

    def get_messages(self, username: str, thread_id: str):
        self.message_calls.append((username, thread_id))
        if self.error is not None:
            raise self.error
        return list(self.messages_by_thread.get(thread_id, []))


def build_request(*, chat_store=None, conversation_db_store=None) -> Request:
    app = FastAPI()
    app.state.chat_store = chat_store or FakeChatStore()
    app.state.conversation_db_store = conversation_db_store
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/threads",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


class AppThreadListDbReadCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_list_helper_keeps_redis_threads_when_flag_disabled(self):
        request = build_request(conversation_db_store=object())
        redis_threads = [{"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 0}]

        with patch.object(app_module.settings, "PERSISTENT_DB_READ_THREADS", False):
            result = await app_module.resolve_thread_summaries_for_read_response(
                request,
                username="alice",
                redis_threads=redis_threads,
            )

        self.assertEqual(result, redis_threads)

    async def test_thread_list_helper_returns_db_threads_when_cutover_enabled_and_summaries_match(self):
        updated_at = datetime(2026, 4, 2, 17, 30, tzinfo=timezone.utc)
        db_store = FakeConversationDbStore(
            threads=[SimpleNamespace(thread_id="default", updated_at=updated_at)],
            messages_by_thread={
                "default": [SimpleNamespace(role="user", content="Привет")],
            },
        )
        request = build_request(conversation_db_store=db_store)
        redis_threads = [{"id": "default", "title": "Привет", "updatedAt": 0, "messageCount": 1}]

        with patch.object(app_module.settings, "PERSISTENT_DB_READ_THREADS", True):
            result = await app_module.resolve_thread_summaries_for_read_response(
                request,
                username="alice",
                redis_threads=redis_threads,
            )

        self.assertEqual(result[0]["id"], "default")
        self.assertEqual(result[0]["title"], "Привет")
        self.assertEqual(result[0]["messageCount"], 1)
        self.assertEqual(db_store.list_calls, ["alice"])
        self.assertEqual(db_store.message_calls, [("alice", "default")])

    async def test_thread_list_helper_falls_back_to_redis_when_summaries_mismatch(self):
        db_store = FakeConversationDbStore(
            threads=[SimpleNamespace(thread_id="default", updated_at=datetime(2026, 4, 2, tzinfo=timezone.utc))],
            messages_by_thread={
                "default": [SimpleNamespace(role="user", content="Из БД")],
            },
        )
        request = build_request(conversation_db_store=db_store)
        redis_threads = [{"id": "default", "title": "Из Redis", "updatedAt": 0, "messageCount": 1}]

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_THREADS", True),
            patch.object(app_module.logger, "warning") as warning_mock,
        ):
            result = await app_module.resolve_thread_summaries_for_read_response(
                request,
                username="alice",
                redis_threads=redis_threads,
            )

        self.assertEqual(result, redis_threads)
        warning_mock.assert_called_once()

    async def test_thread_list_helper_falls_back_to_redis_when_db_read_raises(self):
        request = build_request(
            conversation_db_store=FakeConversationDbStore(error=RuntimeError("boom")),
        )
        redis_threads = [{"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 0}]

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_THREADS", True),
            patch.object(app_module.logger, "exception") as exception_mock,
        ):
            result = await app_module.resolve_thread_summaries_for_read_response(
                request,
                username="alice",
                redis_threads=redis_threads,
            )

        self.assertEqual(result, redis_threads)
        exception_mock.assert_called_once()

    async def test_threads_endpoint_preserves_shape_when_db_cutover_succeeds(self):
        updated_at = datetime(2026, 4, 2, 17, 45, tzinfo=timezone.utc)
        db_store = FakeConversationDbStore(
            threads=[SimpleNamespace(thread_id="default", updated_at=updated_at)],
            messages_by_thread={
                "default": [SimpleNamespace(role="user", content="Привет")],
            },
        )
        request = build_request(conversation_db_store=db_store)
        redis_threads = [{"id": "default", "title": "Привет", "updatedAt": 0, "messageCount": 1}]

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_THREADS", True),
            patch.object(app_module, "load_thread_summaries", AsyncMock(return_value=redis_threads)),
        ):
            response = await app_module.get_chat_threads(
                request,
                current_user={"username": "alice"},
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in payload["threads"]], ["default"])
        self.assertEqual(payload["threads"][0]["title"], "Привет")
        self.assertEqual(payload["threads"][0]["messageCount"], 1)
        self.assertEqual(payload["active_thread_id"], "default")


if __name__ == "__main__":
    unittest.main()

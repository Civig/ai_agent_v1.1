import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

import app as app_module
from persistence.conversation_parity import (
    ConversationThreadParityResult,
    PARITY_CONTENT_MISMATCH,
    PARITY_MATCHED,
)


class FakeChatStore:
    def __init__(self, history: list[dict[str, str]]):
        self.history = history

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, str]]:
        del username, thread_id
        return list(self.history)


class FakeConversationDbStore:
    def __init__(self, messages=None, *, error: Exception | None = None):
        self.messages = list(messages or [])
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def get_messages(self, username: str, thread_id: str):
        self.calls.append((username, thread_id))
        if self.error is not None:
            raise self.error
        return list(self.messages)


def build_request(*, chat_store=None, conversation_db_store=None) -> Request:
    app = FastAPI()
    app.state.chat_store = chat_store
    app.state.conversation_db_store = conversation_db_store
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/threads/default/messages",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
    )


class AppDbReadCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_helper_keeps_redis_history_when_cutover_flag_disabled(self):
        request = build_request(conversation_db_store=object())
        redis_history = [{"role": "user", "content": "A"}]
        shadow_compare_mock = AsyncMock()

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_MESSAGES", False),
            patch.object(
                app_module,
                "maybe_run_shadow_compare_for_conversation_read",
                shadow_compare_mock,
            ),
        ):
            result = await app_module.resolve_thread_messages_for_read_response(
                request,
                username="alice",
                thread_id="default",
                redis_history=redis_history,
            )

        self.assertEqual(result, redis_history)
        shadow_compare_mock.assert_awaited_once_with(
            request,
            username="alice",
            thread_id="default",
            history=redis_history,
        )

    async def test_read_helper_returns_db_history_when_cutover_enabled_and_parity_matches(self):
        redis_history = [{"role": "user", "content": "A"}]
        db_store = FakeConversationDbStore(
            messages=[SimpleNamespace(role="user", content="A")],
        )
        request = build_request(conversation_db_store=db_store)

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_MESSAGES", True),
            patch.object(
                app_module,
                "compare_history_snapshot_to_messages",
                return_value=ConversationThreadParityResult(
                    thread_id="default",
                    status=PARITY_MATCHED,
                    source_message_count=1,
                    db_message_count=1,
                ),
            ),
        ):
            result = await app_module.resolve_thread_messages_for_read_response(
                request,
                username="alice",
                thread_id="default",
                redis_history=redis_history,
            )

        self.assertEqual(result, [{"role": "user", "content": "A"}])
        self.assertEqual(db_store.calls, [("alice", "default")])

    async def test_read_helper_falls_back_to_redis_when_parity_mismatch_detected(self):
        redis_history = [{"role": "user", "content": "A"}]
        db_store = FakeConversationDbStore(
            messages=[SimpleNamespace(role="assistant", content="B")],
        )
        request = build_request(conversation_db_store=db_store)

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_MESSAGES", True),
            patch.object(
                app_module,
                "compare_history_snapshot_to_messages",
                return_value=ConversationThreadParityResult(
                    thread_id="default",
                    status=PARITY_CONTENT_MISMATCH,
                    source_message_count=1,
                    db_message_count=1,
                ),
            ),
            patch.object(app_module.logger, "warning") as warning_mock,
        ):
            result = await app_module.resolve_thread_messages_for_read_response(
                request,
                username="alice",
                thread_id="default",
                redis_history=redis_history,
            )

        self.assertEqual(result, redis_history)
        warning_mock.assert_called_once()

    async def test_read_helper_falls_back_to_redis_when_db_read_raises(self):
        redis_history = [{"role": "user", "content": "A"}]
        request = build_request(
            conversation_db_store=FakeConversationDbStore(error=RuntimeError("boom")),
        )

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_MESSAGES", True),
            patch.object(app_module.logger, "exception") as exception_mock,
        ):
            result = await app_module.resolve_thread_messages_for_read_response(
                request,
                username="alice",
                thread_id="default",
                redis_history=redis_history,
            )

        self.assertEqual(result, redis_history)
        exception_mock.assert_called_once()

    async def test_thread_messages_endpoint_preserves_shape_when_db_cutover_succeeds(self):
        redis_history = [{"role": "user", "content": "A"}]
        request = build_request(
            chat_store=FakeChatStore(redis_history),
            conversation_db_store=FakeConversationDbStore(
                messages=[SimpleNamespace(role="user", content="A")],
            ),
        )
        thread = {"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 1}

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_READ_MESSAGES", True),
            patch.object(app_module, "load_thread_summaries", AsyncMock(return_value=[thread])),
            patch.object(
                app_module,
                "compare_history_snapshot_to_messages",
                return_value=ConversationThreadParityResult(
                    thread_id="default",
                    status=PARITY_MATCHED,
                    source_message_count=1,
                    db_message_count=1,
                ),
            ),
        ):
            response = await app_module.get_chat_thread_messages(
                "default",
                request,
                current_user={"username": "alice"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body),
            {
                "thread": thread,
                "messages": app_module.prepare_messages(redis_history),
                "thread_id": "default",
            },
        )


if __name__ == "__main__":
    unittest.main()

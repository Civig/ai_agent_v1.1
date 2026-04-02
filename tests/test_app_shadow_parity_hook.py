import json
import os
import unittest
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


class AppShadowParityHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_shadow_compare_helper_skips_when_flag_disabled(self):
        request = build_request(conversation_db_store=object())

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_SHADOW_COMPARE", False),
            patch.object(app_module, "compare_history_snapshot_to_store") as compare_mock,
        ):
            await app_module.maybe_run_shadow_compare_for_conversation_read(
                request,
                username="alice",
                thread_id="default",
                history=[{"role": "user", "content": "A"}],
            )

        compare_mock.assert_not_called()

    async def test_shadow_compare_helper_logs_mismatch_without_raising(self):
        request = build_request(conversation_db_store=object())

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_SHADOW_COMPARE", True),
            patch.object(
                app_module,
                "compare_history_snapshot_to_store",
                return_value=ConversationThreadParityResult(
                    thread_id="default",
                    status=PARITY_CONTENT_MISMATCH,
                    source_message_count=1,
                    db_message_count=1,
                ),
            ) as compare_mock,
            patch.object(app_module.logger, "warning") as warning_mock,
        ):
            await app_module.maybe_run_shadow_compare_for_conversation_read(
                request,
                username="alice",
                thread_id="default",
                history=[{"role": "user", "content": "A"}],
            )

        compare_mock.assert_called_once()
        warning_mock.assert_called_once()

    async def test_shadow_compare_helper_swallows_compare_errors(self):
        request = build_request(conversation_db_store=object())

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_SHADOW_COMPARE", True),
            patch.object(
                app_module,
                "compare_history_snapshot_to_store",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(app_module.logger, "exception") as exception_mock,
        ):
            await app_module.maybe_run_shadow_compare_for_conversation_read(
                request,
                username="alice",
                thread_id="default",
                history=[{"role": "user", "content": "A"}],
            )

        exception_mock.assert_called_once()

    async def test_thread_messages_endpoint_returns_same_payload_when_shadow_compare_enabled(self):
        history = [
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуйте"},
        ]
        request = build_request(chat_store=FakeChatStore(history), conversation_db_store=object())
        thread = {"id": "default", "title": "Новый чат", "updatedAt": 0, "messageCount": 2}

        with (
            patch.object(app_module.settings, "PERSISTENT_DB_SHADOW_COMPARE", True),
            patch.object(app_module, "load_thread_summaries", AsyncMock(return_value=[thread])),
            patch.object(
                app_module,
                "compare_history_snapshot_to_store",
                return_value=ConversationThreadParityResult(
                    thread_id="default",
                    status=PARITY_MATCHED,
                    source_message_count=2,
                    db_message_count=2,
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
                "messages": app_module.prepare_messages(history),
                "thread_id": "default",
            },
        )


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
from llm_gateway import AsyncChatStore, DEFAULT_CHAT_THREAD_ID


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def rpush(self, key, *values):
        self.operations.append(("rpush", key, values))
        return self

    def ltrim(self, key, start, stop):
        self.operations.append(("ltrim", key, start, stop))
        return self

    def delete(self, *keys):
        self.operations.append(("delete", keys))
        return self

    async def execute(self):
        results = []
        for operation in self.operations:
            if operation[0] == "rpush":
                _, key, values = operation
                results.append(await self.redis.rpush(key, *values))
            elif operation[0] == "ltrim":
                _, key, start, stop = operation
                results.append(await self.redis.ltrim(key, start, stop))
            elif operation[0] == "delete":
                _, keys = operation
                results.append(await self.redis.delete(*keys))
        self.operations.clear()
        return results


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.zsets = {}

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    async def lrange(self, key, start, stop):
        values = list(self.lists.get(key, []))
        if stop == -1:
            return values[start:]
        return values[start : stop + 1]

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def ltrim(self, key, start, stop):
        values = list(self.lists.get(key, []))
        if stop == -1:
            self.lists[key] = values[start:]
        else:
            self.lists[key] = values[start : stop + 1]
        return True

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.lists:
                removed += 1
                del self.lists[key]
            if key in self.zsets:
                removed += 1
                del self.zsets[key]
        return removed

    async def zadd(self, key, mapping):
        bucket = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            bucket[member] = float(score)
        return len(mapping)

    async def zrem(self, key, *members):
        bucket = self.zsets.get(key, {})
        removed = 0
        for member in members:
            if member in bucket:
                removed += 1
                del bucket[member]
        return removed

    async def zrevrange(self, key, start, stop, withscores=False):
        bucket = self.zsets.get(key, {})
        items = sorted(bucket.items(), key=lambda item: (item[1], item[0]), reverse=True)
        if stop == -1:
            sliced = items[start:]
        else:
            sliced = items[start : stop + 1]
        if withscores:
            return [(member, score) for member, score in sliced]
        return [member for member, _ in sliced]

    async def keys(self, pattern):
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            list_keys = [key for key in self.lists if key.startswith(prefix)]
            zset_keys = [key for key in self.zsets if key.startswith(prefix)]
            return sorted({*list_keys, *zset_keys})
        matches = []
        if pattern in self.lists:
            matches.append(pattern)
        if pattern in self.zsets:
            matches.append(pattern)
        return matches


class AsyncChatStoreThreadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_chat_store_keeps_thread_histories_separate(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()

        await store.append_message("alice", "user", "thread-a-1", thread_id="thread-a")
        await store.append_message("alice", "user", "thread-b-1", thread_id="thread-b")

        history_a = await store.get_history("alice", thread_id="thread-a")
        history_b = await store.get_history("alice", thread_id="thread-b")

        self.assertEqual([message["content"] for message in history_a], ["thread-a-1"])
        self.assertEqual([message["content"] for message in history_b], ["thread-b-1"])
        self.assertEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            ["thread-b", "thread-a"],
        )
        self.assertEqual(
            [thread["message_count"] for thread in await store.list_threads("alice")],
            [1, 1],
        )

    async def test_chat_page_bootstraps_file_chat_history_for_requested_thread_only(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "Summarize\n\n[Вложения: note-a.txt]", thread_id="thread-a")
        await store.append_message("alice", "assistant", "Ответ по документу A", thread_id="thread-a")
        await store.append_message("alice", "user", "Summarize\n\n[Вложения: note-b.txt]", thread_id="thread-b")
        await store.append_message("alice", "assistant", "Ответ по документу B", thread_id="thread-b")

        gateway = type("Gateway", (), {"get_model_catalog": AsyncMock(return_value={"demo": {"name": "demo"}})})()
        request = type(
            "Req",
            (),
            {
                "query_params": {"thread_id": "thread-a"},
                "app": type(
                    "App",
                    (),
                    {
                        "state": type(
                            "State",
                            (),
                            {
                                "chat_store": store,
                                "llm_gateway": gateway,
                                "rate_limiter": type("Limiter", (), {"check": AsyncMock(return_value=None)})(),
                            },
                        )()
                    },
                )(),
            },
        )()

        captured = {}

        def fake_template_response(req, name, context):
            captured["request"] = req
            captured["name"] = name
            captured["context"] = context
            return context

        with patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo", "description": "demo"}),
        ), patch.object(
            app_module.templates,
            "TemplateResponse",
            side_effect=fake_template_response,
        ):
            result = await app_module.chat_page(request, thread_id="thread-a", current_user={"username": "alice"})

        self.assertEqual(result["thread_id"], "thread-a")
        self.assertEqual([message["role"] for message in result["messages"]], ["user", "assistant"])
        self.assertEqual(
            [message["content"] for message in result["messages"]],
            ["Summarize\n\n[Вложения: note-a.txt]", "Ответ по документу A"],
        )
        self.assertEqual(captured["name"], "chat.html")

    async def test_default_thread_reads_legacy_bucket_and_migrates_on_append(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        legacy_key = store.legacy_history_key("alice")
        store.redis.lists[legacy_key] = [
            '{"role":"user","content":"legacy-1","created_at":1}',
            '{"role":"assistant","content":"legacy-2","created_at":2}',
        ]

        history_before = await store.get_history("alice")
        await store.append_message("alice", "user", "legacy-3")
        history_after = await store.get_history("alice")

        self.assertEqual([message["content"] for message in history_before], ["legacy-1", "legacy-2"])
        self.assertEqual([message["content"] for message in history_after], ["legacy-1", "legacy-2", "legacy-3"])
        self.assertNotIn(legacy_key, store.redis.lists)
        self.assertEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            [DEFAULT_CHAT_THREAD_ID],
        )

    async def test_get_history_migrates_legacy_default_bucket_before_any_new_append(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        legacy_key = store.legacy_history_key("alice")
        store.redis.lists[legacy_key] = [
            '{"role":"user","content":"legacy-read-1","created_at":10}',
            '{"role":"assistant","content":"legacy-read-2","created_at":11}',
        ]

        history = await store.get_history("alice")

        self.assertEqual(
            history,
            [
                {"role": "user", "content": "legacy-read-1"},
                {"role": "assistant", "content": "legacy-read-2"},
            ],
        )
        self.assertNotIn(legacy_key, store.redis.lists)
        self.assertEqual(
            store.redis.lists[store.history_key("alice", DEFAULT_CHAT_THREAD_ID)],
            [
                '{"role":"user","content":"legacy-read-1","created_at":10}',
                '{"role":"assistant","content":"legacy-read-2","created_at":11}',
            ],
        )
        self.assertEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            [DEFAULT_CHAT_THREAD_ID],
        )

    async def test_restore_chat_history_restores_only_requested_thread(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "thread-a-original-user", thread_id="thread-a")
        await store.append_message("alice", "assistant", "thread-a-original-assistant", thread_id="thread-a")
        await store.append_message("alice", "user", "thread-b-user", thread_id="thread-b")
        snapshot = await store.get_history("alice", thread_id="thread-a")

        await store.append_message("alice", "user", "thread-a-transient-user", thread_id="thread-a")
        await store.append_message("alice", "assistant", "thread-a-transient-assistant", thread_id="thread-a")

        await app_module.restore_chat_history(store, "alice", "thread-a", snapshot)

        self.assertEqual(await store.get_history("alice", thread_id="thread-a"), snapshot)
        self.assertEqual(
            await store.get_history("alice", thread_id="thread-b"),
            [{"role": "user", "content": "thread-b-user"}],
        )

    async def test_clear_history_keeps_requested_thread_in_registry_by_default(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "thread-a-1", thread_id="thread-a")
        await store.append_message("alice", "assistant", "thread-a-2", thread_id="thread-a")
        await store.append_message("alice", "user", "thread-b-1", thread_id="thread-b")

        await store.clear_history("alice", thread_id="thread-a")

        self.assertEqual(await store.get_history("alice", thread_id="thread-a"), [])
        self.assertEqual(
            await store.get_history("alice", thread_id="thread-b"),
            [{"role": "user", "content": "thread-b-1"}],
        )
        self.assertCountEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            ["thread-a", "thread-b"],
        )

    async def test_clear_history_can_remove_thread_from_registry_when_requested(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "thread-a-1", thread_id="thread-a")
        await store.append_message("alice", "user", "thread-b-1", thread_id="thread-b")

        await store.clear_history("alice", thread_id="thread-a", preserve_thread=False)

        self.assertEqual(await store.get_history("alice", thread_id="thread-a"), [])
        self.assertEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            ["thread-b"],
        )

    async def test_restore_chat_history_restores_only_requested_thread(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        original_thread_a = [
            {"role": "user", "content": "thread-a-user"},
            {"role": "assistant", "content": "thread-a-assistant"},
        ]
        original_thread_b = [
            {"role": "user", "content": "thread-b-user"},
            {"role": "assistant", "content": "thread-b-assistant"},
        ]

        for message in original_thread_a:
            await store.append_message("alice", message["role"], message["content"], thread_id="thread-a")
        for message in original_thread_b:
            await store.append_message("alice", message["role"], message["content"], thread_id="thread-b")

        await store.append_message("alice", "user", "transient-file-request", thread_id="thread-a")
        await app_module.restore_chat_history(store, "alice", "thread-a", original_thread_a)

        self.assertEqual(await store.get_history("alice", thread_id="thread-a"), original_thread_a)
        self.assertEqual(await store.get_history("alice", thread_id="thread-b"), original_thread_b)


class ChatThreadBackendContractTests(unittest.IsolatedAsyncioTestCase):
    def build_request(self, *, json_payload=None, query_params=None, chat_store=None, gateway=None):
        return type(
            "Req",
            (),
            {
                "query_params": query_params or {},
                "app": type(
                    "App",
                    (),
                    {
                        "state": type(
                            "State",
                            (),
                            {
                                "chat_store": chat_store,
                                "llm_gateway": gateway,
                                "rate_limiter": type("Limiter", (), {"check": AsyncMock(return_value=None)})(),
                            },
                        )()
                    },
                )(),
                "json": AsyncMock(return_value=json_payload or {}),
            },
        )()

    async def test_api_chat_uses_thread_scoped_history_and_enqueue_payload(self):
        gateway = type("Gateway", (), {})()
        gateway.get_queue_pressure = AsyncMock(return_value={"queue_depth": 0, "threshold": 10})
        gateway.get_model_catalog = AsyncMock(return_value={"demo": {"name": "demo"}})
        gateway.enqueue_job = AsyncMock(return_value="job-1")

        chat_store = type("ChatStore", (), {})()
        chat_store.get_history = AsyncMock(return_value=[{"role": "user", "content": "earlier"}])
        chat_store.append_message = AsyncMock(return_value=None)

        request = self.build_request(
            json_payload={"prompt": "hello", "thread_id": "thread-b"},
            chat_store=chat_store,
            gateway=gateway,
        )

        with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ):
            response = await app_module.api_chat(request, current_user={"username": "alice"})

        self.assertEqual(response.status_code, 200)
        chat_store.get_history.assert_awaited_once_with("alice", thread_id="thread-b")
        chat_store.append_message.assert_awaited_once_with("alice", "user", "hello", thread_id="thread-b")
        self.assertEqual(gateway.enqueue_job.await_args.kwargs["thread_id"], "thread-b")

    async def test_clear_chat_only_clears_requested_thread(self):
        chat_store = type("ChatStore", (), {})()
        chat_store.clear_history = AsyncMock(return_value=None)
        request = self.build_request(json_payload={"thread_id": "thread-clear"}, chat_store=chat_store, gateway=None)

        with patch.object(app_module, "enforce_csrf", return_value=None):
            response = await app_module.clear_chat(request, current_user={"username": "alice"})

        self.assertEqual(response.status_code, 200)
        chat_store.clear_history.assert_awaited_once_with("alice", thread_id="thread-clear")
        self.assertIn(b'"thread_id":"thread-clear"', response.body)

    async def test_chat_page_bootstraps_requested_thread_history(self):
        chat_store = type("ChatStore", (), {})()
        chat_store.list_threads = AsyncMock(
            return_value=[
                {"thread_id": "thread-page", "updated_at": 10, "title": "Тред страницы", "message_count": 1},
                {"thread_id": "thread-else", "updated_at": 5, "title": "Другой тред", "message_count": 0},
            ]
        )
        chat_store.get_history = AsyncMock(return_value=[{"role": "user", "content": "thread message"}])
        gateway = type("Gateway", (), {"get_model_catalog": AsyncMock(return_value={"demo": {"name": "demo"}})})()
        request = self.build_request(query_params={"thread_id": "thread-page"}, chat_store=chat_store, gateway=gateway)

        captured = {}

        def fake_template_response(req, name, context):
            captured["request"] = req
            captured["name"] = name
            captured["context"] = context
            return context

        with patch.object(app_module, "resolve_runtime_model", AsyncMock(return_value={"key": "demo", "name": "demo", "description": "demo"})), patch.object(
            app_module.templates,
            "TemplateResponse",
            side_effect=fake_template_response,
        ):
            result = await app_module.chat_page(request, thread_id="thread-page", current_user={"username": "alice"})

        self.assertEqual(result["thread_id"], "thread-page")
        self.assertEqual(
            result["threads"],
            [
                {"id": "thread-page", "title": "Тред страницы", "updatedAt": 10000, "messageCount": 1},
                {"id": "thread-else", "title": "Другой тред", "updatedAt": 5000, "messageCount": 0},
            ],
        )
        self.assertEqual(captured["name"], "chat.html")
        chat_store.list_threads.assert_awaited_once_with("alice")
        chat_store.get_history.assert_awaited_once_with("alice", thread_id="thread-page")

    async def test_chat_page_creates_real_default_thread_when_server_has_no_threads(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        gateway = type("Gateway", (), {"get_model_catalog": AsyncMock(return_value={"demo": {"name": "demo"}})})()
        request = self.build_request(query_params={}, chat_store=store, gateway=gateway)

        with patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo", "description": "demo"}),
        ), patch.object(
            app_module.templates,
            "TemplateResponse",
            side_effect=lambda req, name, context: context,
        ):
            result = await app_module.chat_page(request, current_user={"username": "alice"})

        self.assertEqual(result["thread_id"], DEFAULT_CHAT_THREAD_ID)
        self.assertEqual(result["threads"][0]["id"], DEFAULT_CHAT_THREAD_ID)
        self.assertEqual([thread["thread_id"] for thread in await store.list_threads("alice")], [DEFAULT_CHAT_THREAD_ID])

    async def test_api_chat_uses_deterministic_default_thread_when_missing(self):
        gateway = type("Gateway", (), {})()
        gateway.get_queue_pressure = AsyncMock(return_value={"queue_depth": 0, "threshold": 10})
        gateway.get_model_catalog = AsyncMock(return_value={"demo": {"name": "demo"}})
        gateway.enqueue_job = AsyncMock(return_value="job-1")

        chat_store = type("ChatStore", (), {})()
        chat_store.get_history = AsyncMock(return_value=[])
        chat_store.append_message = AsyncMock(return_value=None)

        request = self.build_request(json_payload={"prompt": "hello"}, chat_store=chat_store, gateway=gateway)

        with patch.object(app_module, "enforce_csrf", return_value=None), patch.object(
            app_module,
            "resolve_runtime_model",
            AsyncMock(return_value={"key": "demo", "name": "demo"}),
        ):
            response = await app_module.api_chat(request, current_user={"username": "alice"})

        self.assertEqual(response.status_code, 200)
        chat_store.get_history.assert_awaited_once_with("alice", thread_id=DEFAULT_CHAT_THREAD_ID)
        chat_store.append_message.assert_awaited_once_with("alice", "user", "hello", thread_id=DEFAULT_CHAT_THREAD_ID)
        self.assertEqual(gateway.enqueue_job.await_args.kwargs["thread_id"], DEFAULT_CHAT_THREAD_ID)

    async def test_api_threads_returns_backend_truth_with_active_thread(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "thread-a-1", thread_id="thread-a")
        await store.create_thread("alice", thread_id="thread-empty")

        request = self.build_request(query_params={"thread_id": "thread-empty"}, chat_store=store, gateway=None)
        response = await app_module.get_chat_threads(request, current_user={"username": "alice"})
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["active_thread_id"], "thread-empty")
        self.assertCountEqual(
            [thread["id"] for thread in payload["threads"]],
            ["thread-a", "thread-empty"],
        )

    async def test_create_chat_thread_creates_real_server_thread_entity(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        request = self.build_request(chat_store=store, gateway=None)

        with patch.object(app_module, "enforce_csrf", return_value=None):
            response = await app_module.create_chat_thread(request, current_user={"username": "alice"})

        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["thread"]["id"].startswith("thread-"))
        self.assertEqual(payload["active_thread_id"], payload["thread"]["id"])
        self.assertEqual(
            [thread["thread_id"] for thread in await store.list_threads("alice")],
            [payload["thread"]["id"]],
        )

    async def test_api_thread_messages_returns_requested_thread_history(self):
        store = AsyncChatStore("redis://test")
        store.redis = FakeRedis()
        await store.append_message("alice", "user", "thread-a-user", thread_id="thread-a")
        await store.append_message("alice", "assistant", "thread-a-assistant", thread_id="thread-a")
        await store.append_message("alice", "user", "thread-b-user", thread_id="thread-b")

        request = self.build_request(chat_store=store, gateway=None)
        response = await app_module.get_chat_thread_messages("thread-a", request, current_user={"username": "alice"})
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["thread"]["id"], "thread-a")
        self.assertEqual(
            [message["content"] for message in payload["messages"]],
            ["thread-a-user", "thread-a-assistant"],
        )
        self.assertEqual(payload["thread_id"], "thread-a")


if __name__ == "__main__":
    unittest.main()

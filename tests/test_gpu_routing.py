import io
import json
import os
import unittest
from collections import defaultdict
from unittest.mock import AsyncMock, patch

from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import app as app_module
from llm_gateway import LLMGateway, WORKLOAD_CHAT


MODEL_CATALOG = {
    "demo-model": {
        "name": "demo-model",
        "description": "Demo model",
        "size": str(1024 * 1024 * 1024),
        "status": "active",
    }
}


class FakeAsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def set(self, key, value, ex=None):
        self.operations.append(("set", key, value, ex))
        return self

    def rpush(self, key, *values):
        self.operations.append(("rpush", key, values))
        return self

    def xadd(self, key, fields):
        self.operations.append(("xadd", key, fields))
        return self

    def expire(self, key, ttl):
        self.operations.append(("expire", key, ttl))
        return self

    def hincrby(self, key, field, amount):
        self.operations.append(("hincrby", key, field, amount))
        return self

    async def execute(self):
        results = []
        for operation in self.operations:
            name = operation[0]
            if name == "set":
                _, key, value, ex = operation
                results.append(await self.redis.set(key, value, ex=ex))
            elif name == "rpush":
                _, key, values = operation
                results.append(await self.redis.rpush(key, *values))
            elif name == "xadd":
                _, key, fields = operation
                results.append(await self.redis.xadd(key, fields))
            elif name == "expire":
                _, key, ttl = operation
                results.append(await self.redis.expire(key, ttl))
            elif name == "hincrby":
                _, key, field, amount = operation
                results.append(await self.redis.hincrby(key, field, amount))
        self.operations.clear()
        return results


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = defaultdict(list)
        self.hashes = defaultdict(dict)
        self.streams = defaultdict(list)
        self.zsets = defaultdict(dict)

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def lock(self, key, timeout=5):
        return FakeAsyncLock()

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def rpush(self, key, *values):
        self.lists[key].extend(values)
        return len(self.lists[key])

    async def lrange(self, key, start, end):
        items = list(self.lists.get(key, []))
        if end == -1:
            end = len(items) - 1
        return items[start : end + 1]

    async def lrem(self, key, count, value):
        items = list(self.lists.get(key, []))
        removed = 0
        kept = []
        for item in items:
            if item == value and (count <= 0 or removed < count):
                removed += 1
                continue
            kept.append(item)
        self.lists[key] = kept
        return removed

    async def xadd(self, key, fields):
        entry_id = f"{len(self.streams[key]) + 1}-0"
        self.streams[key].append((entry_id, fields))
        return entry_id

    async def expire(self, key, ttl):
        return True

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, mapping):
        self.hashes[key].update(mapping)
        return True

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)
        return True

    async def hincrby(self, key, field, amount):
        current = int(self.hashes[key].get(field, 0))
        current += amount
        self.hashes[key][field] = current
        return current

    async def brpoplpush(self, source, destination, timeout=0):
        items = self.lists.get(source, [])
        if not items:
            return None
        value = items.pop()
        self.lists[destination].insert(0, value)
        return value

    async def zadd(self, key, mapping):
        self.zsets[key].update(mapping)
        return len(mapping)

    async def zrem(self, key, *members):
        removed = 0
        for member in members:
            if member in self.zsets.get(key, {}):
                removed += 1
                del self.zsets[key][member]
        return removed


class FakeRateLimiter:
    async def check(self, subject):
        return None


class FakeChatStore:
    def __init__(self):
        self.history = defaultdict(list)

    async def get_history(self, username, thread_id=None):
        del thread_id
        return list(self.history[username])

    async def append_message(self, username, role, content, thread_id=None):
        del thread_id
        self.history[username].append({"role": role, "content": content})

    async def clear_history(self, username, thread_id=None):
        del thread_id
        self.history[username].clear()


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def build_gateway(self) -> LLMGateway:
        gateway = LLMGateway("redis://test")
        gateway.redis = FakeRedis()
        gateway.available = True
        gateway.get_total_pending_jobs = AsyncMock(return_value=0)
        gateway._dynamic_queue_limit = AsyncMock(return_value=100)
        gateway.get_model_catalog = AsyncMock(return_value=MODEL_CATALOG)
        return gateway

    def set_topology(self, gateway: LLMGateway, *, workers, targets) -> None:
        gateway.list_active_workers = AsyncMock(return_value=workers)
        gateway.list_active_targets = AsyncMock(return_value=targets)

    async def test_default_mode_routes_jobs_to_cpu(self):
        gateway = self.build_gateway()
        self.set_topology(gateway, workers=[], targets=[])

        with patch.dict(os.environ, {"GPU_ENABLED": "false"}, clear=False):
            job_id = await gateway.enqueue_job(
                username="alice",
                model_key="demo-model",
                model_name="demo-model",
                prompt="hello",
                history=[],
            )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["target_kind"], "cpu")

    async def test_gpu_enabled_without_gpu_worker_falls_back_to_cpu(self):
        gateway = self.build_gateway()
        self.set_topology(
            gateway,
            workers=[{"worker_pool": WORKLOAD_CHAT, "target_id": "cpu-target"}],
            targets=[{"target_id": "cpu-target", "target_kind": "cpu"}],
        )

        with patch.dict(os.environ, {"GPU_ENABLED": "true"}, clear=False):
            job_id = await gateway.enqueue_job(
                username="alice",
                model_key="demo-model",
                model_name="demo-model",
                prompt="hello",
                history=[],
            )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["target_kind"], "cpu")

    async def test_gpu_worker_routes_jobs_to_gpu(self):
        gateway = self.build_gateway()
        self.set_topology(
            gateway,
            workers=[{"worker_pool": WORKLOAD_CHAT, "target_id": "gpu-target"}],
            targets=[{"target_id": "gpu-target", "target_kind": "gpu"}],
        )

        with patch.dict(os.environ, {"GPU_ENABLED": "true"}, clear=False):
            job_id = await gateway.enqueue_job(
                username="alice",
                model_key="demo-model",
                model_name="demo-model",
                prompt="hello",
                history=[],
            )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["target_kind"], "gpu")

        usage = {
            "reserved_vram_mb": 0,
            "reserved_ram_mb": 0,
            "reserved_tokens": 0,
            "active_jobs": 0,
            "reserved_tokens_chat": 0,
            "reserved_tokens_siem": 0,
            "reserved_tokens_batch": 0,
        }
        cpu_target = {
            "target_id": "cpu-target",
            "target_kind": "cpu",
            "base_capacity_tokens": 128,
            "cpu_count": 8,
            "cpu_percent": 0.0,
            "ram_free_mb": 32768,
            "loaded_models": [],
            "pinned_models": [],
        }
        gpu_target = {
            "target_id": "gpu-target",
            "target_kind": "gpu",
            "base_capacity_tokens": 128,
            "vram_free_mb": 32768,
            "loaded_models": [],
            "pinned_models": [],
        }

        cpu_admission = await gateway._evaluate_target_admission(job, cpu_target, usage)
        gpu_admission = await gateway._evaluate_target_admission(job, gpu_target, usage)

        self.assertFalse(cpu_admission["admit"])
        self.assertTrue(gpu_admission["admit"])

    async def test_file_chat_upload_keeps_routing_and_upload_flow(self):
        gateway = self.build_gateway()
        gateway.get_queue_pressure = AsyncMock(return_value={"queue_depth": 0, "threshold": 10})
        self.set_topology(
            gateway,
            workers=[{"worker_pool": WORKLOAD_CHAT, "target_id": "cpu-target"}],
            targets=[{"target_id": "cpu-target", "target_kind": "cpu"}],
        )

        app_module.app.state.llm_gateway = gateway
        app_module.app.state.chat_store = FakeChatStore()
        app_module.app.state.rate_limiter = FakeRateLimiter()
        current_user = {
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.com",
            "groups": ["users"],
            "model": "demo-model",
            "model_key": "demo-model",
            "model_description": "Demo model",
        }
        upload = UploadFile(
            file=io.BytesIO(b"hello from file"),
            filename="note.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat_with_files",
            "scheme": "http",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"origin", b"http://testserver"),
                (b"x-csrf-token", b"csrf-token"),
                (b"cookie", b"csrf_token=csrf-token"),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
            "app": app_module.app,
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive)

        async def fake_wait_for_terminal_job(gateway_obj, job_id, timeout_seconds):
            return {"status": "completed", "result": "Готово"}

        with patch.dict(os.environ, {"GPU_ENABLED": "true"}, clear=False):
            with patch.object(
                app_module,
                "resolve_runtime_model",
                AsyncMock(return_value={"key": "demo-model", "name": "demo-model", "description": "Demo model"}),
            ), patch.object(app_module, "wait_for_terminal_job", fake_wait_for_terminal_job):
                response = await app_module.api_chat_with_files(
                    request=request,
                    message="summarize",
                    model="demo-model",
                    files=[upload],
                    current_user=current_user,
                )

        self.assertEqual(response.status_code, 200, response.body.decode("utf-8", errors="ignore"))
        payload = json.loads(response.body)
        self.assertIn("job_id", payload)
        self.assertEqual(payload["files"][0]["name"], "note.txt")

        job = await gateway.get_job(payload["job_id"])
        self.assertEqual(job["target_kind"], "cpu")
        self.assertIn("hello from file", job["prompt"])


if __name__ == "__main__":
    unittest.main()

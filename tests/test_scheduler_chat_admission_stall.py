import os
import unittest
from collections import defaultdict
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

from llm_gateway import JOB_STATUS_ADMITTED, JOB_STATUS_QUEUED, LLMGateway, WORKLOAD_CHAT


MODEL_CATALOG = {
    "demo-model": {
        "name": "demo-model",
        "description": "Demo model",
        "size": str(6 * 1024 * 1024 * 1024),
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


class SchedulerChatAdmissionStallTests(unittest.IsolatedAsyncioTestCase):
    def build_gateway(self) -> LLMGateway:
        gateway = LLMGateway("redis://test")
        gateway.redis = FakeRedis()
        gateway.available = True
        gateway.get_total_pending_jobs = AsyncMock(return_value=0)
        gateway._dynamic_queue_limit = AsyncMock(return_value=100)
        gateway.get_model_catalog = AsyncMock(return_value=MODEL_CATALOG)
        return gateway

    async def test_idle_cpu_chat_job_reaches_admission_and_dispatch_under_cold_start_override(self):
        gateway = self.build_gateway()
        job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="hello",
            history=[],
            workload_class=WORKLOAD_CHAT,
        )
        queue_key = gateway.pending_queue_key(WORKLOAD_CHAT, "p1")
        target = {
            "target_id": "cpu-target",
            "target_kind": "cpu",
            "base_capacity_tokens": 64,
            "cpu_count": 8,
            "cpu_percent": 0.0,
            "ram_free_mb": 8192,
            "loaded_models": [],
            "pinned_models": [],
        }

        admitted = await gateway.try_admit_job(job_id, queue_key, target)

        job = await gateway.get_job(job_id)
        dispatch_queue = gateway.redis.lists[gateway.dispatch_queue_key("chat", "cpu-target")]
        active_jobs = gateway.redis.zsets[gateway.ACTIVE_JOBS_ZSET]
        self.assertTrue(admitted)
        self.assertEqual(job["status"], JOB_STATUS_ADMITTED)
        self.assertEqual(job["assigned_target_id"], "cpu-target")
        self.assertIsNotNone(job["admitted_at"])
        self.assertTrue(job["profile"]["cpu_cold_start_ram_override"])
        self.assertEqual(dispatch_queue, [job_id])
        self.assertIn(job_id, active_jobs)

    async def test_busy_cpu_target_still_denies_chat_job_when_capacity_is_already_in_use(self):
        gateway = self.build_gateway()
        target_usage_key = gateway.target_usage_key("cpu-target")
        gateway.redis.hashes[target_usage_key] = {
            "reserved_tokens": 8,
            "active_jobs": 1,
            "reserved_tokens_chat": 8,
            "reserved_tokens_siem": 0,
            "reserved_tokens_batch": 0,
            "reserved_ram_mb": 2048,
            "reserved_vram_mb": 0,
        }
        job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="hello",
            history=[],
            workload_class=WORKLOAD_CHAT,
        )
        queue_key = gateway.pending_queue_key(WORKLOAD_CHAT, "p1")
        target = {
            "target_id": "cpu-target",
            "target_kind": "cpu",
            "base_capacity_tokens": 64,
            "cpu_count": 8,
            "cpu_percent": 0.0,
            "ram_free_mb": 8192,
            "loaded_models": [],
            "pinned_models": [],
        }

        admitted = await gateway.try_admit_job(job_id, queue_key, target)

        job = await gateway.get_job(job_id)
        dispatch_queue = gateway.redis.lists[gateway.dispatch_queue_key("chat", "cpu-target")]
        self.assertFalse(admitted)
        self.assertEqual(job["status"], JOB_STATUS_QUEUED)
        self.assertIsNone(job["assigned_target_id"])
        self.assertEqual(dispatch_queue, [])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import types
import unittest
from collections import defaultdict
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

fake_httpx = types.SimpleNamespace(
    AsyncClient=object,
    Timeout=lambda *args, **kwargs: None,
    Limits=lambda *args, **kwargs: None,
    ConnectError=RuntimeError,
    ReadTimeout=TimeoutError,
    RemoteProtocolError=RuntimeError,
    HTTPStatusError=RuntimeError,
    Response=object,
)
sys.modules.setdefault("httpx", fake_httpx)

import config as config_module
import worker as worker_module
from llm_gateway import (
    JOB_KIND_FILE_CHAT,
    JOB_KIND_PARSE,
    LLMGateway,
    WORKLOAD_CHAT,
    WORKLOAD_PARSE,
    WORKER_POOL_PARSER,
    extract_job_observability_fields,
    normalize_workload_class,
    worker_pool_for_workload,
)


MODEL_CATALOG = {
    "demo-model": {
        "name": "demo-model",
        "description": "Demo model",
        "size": str(1024 * 1024 * 1024),
        "status": "active",
    }
}


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
        self.operations.clear()
        return results


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = defaultdict(list)
        self.streams = defaultdict(list)
        self.zsets = defaultdict(dict)

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def rpush(self, key, *values):
        self.lists[key].extend(values)
        return len(self.lists[key])

    async def xadd(self, key, fields):
        entry_id = f"{len(self.streams[key]) + 1}-0"
        self.streams[key].append((entry_id, fields))
        return entry_id

    async def expire(self, key, ttl):
        return True

    async def zrem(self, key, *members):
        for member in members:
            self.zsets.get(key, {}).pop(member, None)
        return True

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


class ConfigGroundworkTests(unittest.TestCase):
    def test_parser_stage_settings_have_safe_defaults(self):
        settings = config_module.Settings(SECRET_KEY="x" * 40, COOKIE_SECURE=False)

        self.assertFalse(settings.ENABLE_PARSER_STAGE)
        self.assertEqual(settings.PARSER_STAGING_ROOT, "/tmp/corporate-ai-parser-staging")
        self.assertEqual(settings.PARSER_JOB_TIMEOUT_SECONDS, 300)
        self.assertEqual(settings.PARSER_STAGING_TTL_SECONDS, 3600)

    def test_parser_worker_pool_is_accepted(self):
        settings = config_module.Settings(SECRET_KEY="x" * 40, COOKIE_SECURE=False, WORKER_POOL="parser")

        self.assertEqual(settings.WORKER_POOL, "parser")
        self.assertEqual(settings.worker_supported_workloads, ["parse"])


class GatewayGroundworkTests(unittest.IsolatedAsyncioTestCase):
    def build_gateway(self) -> LLMGateway:
        gateway = LLMGateway("redis://test")
        gateway.redis = FakeRedis()
        gateway.available = True
        gateway.get_total_pending_jobs = AsyncMock(return_value=0)
        gateway._dynamic_queue_limit = AsyncMock(return_value=100)
        gateway.get_model_catalog = AsyncMock(return_value=MODEL_CATALOG)
        gateway.list_active_workers = AsyncMock(return_value=[{"worker_pool": WORKER_POOL_PARSER, "target_id": "cpu-target"}])
        gateway.list_active_targets = AsyncMock(return_value=[{"target_id": "cpu-target", "target_kind": "cpu"}])
        return gateway

    async def test_parse_job_schema_persists_parser_specific_fields(self):
        gateway = self.build_gateway()

        job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            root_job_id="root-1",
            parent_job_id="parent-1",
            staging_id="staging-1",
            parser_metadata={"files": [{"name": "note.txt", "size": 5}], "phase": "parser"},
        )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["job_kind"], JOB_KIND_PARSE)
        self.assertEqual(job["workload_class"], WORKLOAD_PARSE)
        self.assertEqual(job["worker_pool"], WORKER_POOL_PARSER)
        self.assertEqual(job["root_job_id"], "root-1")
        self.assertEqual(job["parent_job_id"], "parent-1")
        self.assertEqual(job["staging_id"], "staging-1")
        self.assertEqual(job["parser_metadata"]["phase"], "parser")
        self.assertEqual(job["parser_metadata"]["files"][0]["name"], "note.txt")

    async def test_existing_file_chat_job_shape_remains_unchanged(self):
        gateway = self.build_gateway()

        job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="hello",
            history=[],
            job_kind=JOB_KIND_FILE_CHAT,
            workload_class=WORKLOAD_CHAT,
            file_chat={"files": [{"name": "note.txt", "size": 5}]},
        )

        job = await gateway.get_job(job_id)
        self.assertEqual(job["job_kind"], JOB_KIND_FILE_CHAT)
        self.assertEqual(job["workload_class"], WORKLOAD_CHAT)
        self.assertEqual(job["worker_pool"], WORKLOAD_CHAT)
        self.assertIsNone(job["root_job_id"])
        self.assertIsNone(job["parent_job_id"])
        self.assertIsNone(job["staging_id"])
        self.assertIsNone(job["parser_metadata"])

    def test_parser_workload_is_first_class_and_not_collapsed_to_chat(self):
        self.assertEqual(normalize_workload_class(WORKLOAD_PARSE), WORKLOAD_PARSE)
        self.assertEqual(worker_pool_for_workload(WORKLOAD_PARSE), WORKER_POOL_PARSER)

        fields = extract_job_observability_fields(
            {
                "id": "parse-1",
                "username": "alice",
                "job_kind": JOB_KIND_PARSE,
                "workload_class": WORKLOAD_PARSE,
                "target_kind": "cpu",
                "parser_metadata": {"files": [{"name": "a.txt"}]},
            }
        )

        self.assertEqual(fields["job_kind"], JOB_KIND_PARSE)
        self.assertEqual(fields["workload_class"], WORKLOAD_PARSE)
        self.assertEqual(fields["file_count"], 1)


class WorkerGroundworkTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_pool_initializes_without_ollama_runtime(self):
        with patch.object(worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER):
            worker = worker_module.LLMWorker()

        self.assertTrue(worker.is_parser_pool)
        self.assertIsNone(worker.ollama)

    async def test_parser_pool_start_skips_model_catalog_refresh(self):
        with patch.object(worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER):
            worker = worker_module.LLMWorker()

        worker.gateway = type("Gateway", (), {})()
        worker.gateway.connect = AsyncMock(return_value=None)
        worker.gateway.close = AsyncMock(return_value=None)

        worker.chat_store = type("ChatStore", (), {})()
        worker.chat_store.connect = AsyncMock(return_value=None)
        worker.chat_store.close = AsyncMock(return_value=None)

        worker.run = AsyncMock(return_value=None)
        worker.heartbeat_loop = AsyncMock(return_value=None)
        worker.lease_loop = AsyncMock(return_value=None)
        worker.refresh_model_catalog_loop = AsyncMock(return_value=None)

        await worker.start()

        worker.gateway.connect.assert_awaited_once()
        worker.chat_store.connect.assert_awaited_once()
        worker.run.assert_awaited_once()
        worker.refresh_model_catalog_loop.assert_not_awaited()

    async def test_parser_jobs_fail_safely_while_feature_flag_is_off(self):
        with patch.object(worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER), patch.object(
            worker_module.settings, "ENABLE_PARSER_STAGE", False
        ):
            worker = worker_module.LLMWorker()

        worker.gateway = type("Gateway", (), {})()
        worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
        worker.gateway.mark_job_failed = AsyncMock(return_value=None)
        worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

        await worker.process_job(
            {
                "id": "parse-job-1",
                "username": "alice",
                "job_kind": JOB_KIND_PARSE,
                "workload_class": WORKLOAD_PARSE,
            }
        )

        worker.gateway.mark_job_failed.assert_awaited_once()
        self.assertIn("Parser stage is disabled", worker.gateway.mark_job_failed.await_args.args[1])
        worker.gateway.mark_job_cancelled.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

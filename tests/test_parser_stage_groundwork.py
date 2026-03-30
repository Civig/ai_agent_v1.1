import json
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
    DEADLINE_EXCEEDED_ERROR,
    GENERIC_CHAT_ERROR,
    JOB_KIND_FILE_CHAT,
    JOB_KIND_PARSE,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    LIFECYCLE_STAGE_CHILD_CANCELLED,
    LIFECYCLE_STAGE_CHILD_COMPLETED,
    LIFECYCLE_STAGE_CHILD_ENQUEUED,
    LIFECYCLE_STAGE_CHILD_FAILED,
    LLMGateway,
    LIFECYCLE_STAGE_PARSER_PREPARED,
    ParserChildEnqueueCancelled,
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
        self.streams = defaultdict(list)
        self.zsets = defaultdict(dict)
        self.hashes = defaultdict(dict)

    def lock(self, key, timeout=5):
        class _Lock:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Lock()

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

    async def xread(self, streams, block=None, count=None):
        batches = []
        for key, last_id in streams.items():
            entries = []
            for entry_id, fields in self.streams.get(key, []):
                if self._compare_stream_ids(entry_id, last_id) > 0:
                    entries.append((entry_id, fields))
            if count is not None:
                entries = entries[:count]
            if entries:
                batches.append((key, entries))
        return batches

    async def expire(self, key, ttl):
        return True

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hincrby(self, key, field, amount):
        current = int(self.hashes[key].get(field, 0))
        self.hashes[key][field] = str(current + amount)
        return current + amount

    async def hset(self, key, mapping=None, **kwargs):
        payload = dict(mapping or {})
        payload.update(kwargs)
        for field, value in payload.items():
            self.hashes[key][field] = str(value)
        return True

    async def hdel(self, key, *fields):
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)
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

    async def zadd(self, key, mapping):
        self.zsets[key].update(mapping)
        return len(mapping)

    async def zrangebyscore(self, key, minimum, maximum):
        items = self.zsets.get(key, {})
        return [
            member
            for member, score in sorted(items.items(), key=lambda item: item[1])
            if minimum <= score <= maximum
        ]

    @staticmethod
    def _compare_stream_ids(left, right):
        left_major, _, left_minor = left.partition("-")
        right_major, _, right_minor = right.partition("-")
        return (int(left_major), int(left_minor or 0)) > (int(right_major), int(right_minor or 0)) and 1 or (
            (int(left_major), int(left_minor or 0)) < (int(right_major), int(right_minor or 0)) and -1 or 0
        )


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
        self.assertIsNone(job["child_job_id"])
        self.assertIsNone(job["lifecycle_stage"])

    async def test_child_enqueue_once_persists_root_child_linkage(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )

        child_job_id, created = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [{"role": "user", "content": "Earlier"}],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )

        self.assertTrue(created)
        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        self.assertEqual(root_job["child_job_id"], child_job_id)
        self.assertEqual(child_job["job_kind"], JOB_KIND_FILE_CHAT)
        self.assertEqual(child_job["root_job_id"], root_job_id)
        self.assertEqual(child_job["parent_job_id"], root_job_id)
        self.assertEqual(child_job["staging_id"], "staging-1")

    async def test_child_enqueue_once_is_idempotent_and_reuses_existing_child(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )

        first_child_id, first_created = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        second_child_id, second_created = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_child_id, second_child_id)
        queue_key = gateway.pending_queue_key(WORKLOAD_CHAT, "p1")
        self.assertEqual(self.build_gateway().redis.lists.get(queue_key, []), [])
        self.assertEqual(gateway.redis.lists[queue_key], [first_child_id])

    async def test_mark_job_waiting_on_child_preserves_non_terminal_root(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        job = await gateway.get_job(root_job_id)
        job.update(
            {
                "status": "running",
                "assigned_target_id": "cpu-target",
                "assigned_worker_id": "worker-1",
                "lease_until": 12345,
                "reserved_tokens": 1,
                "reserved_ram_mb": 16,
            }
        )
        await gateway.save_job(job)
        gateway._release_reserved_capacity = AsyncMock(return_value=None)
        gateway._remove_from_processing = AsyncMock(return_value=None)

        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id="child-1",
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
            parser_metadata_updates={"phase": LIFECYCLE_STAGE_CHILD_ENQUEUED},
            worker_id="worker-1",
        )

        updated = await gateway.get_job(root_job_id)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["child_job_id"], "child-1")
        self.assertEqual(updated["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_ENQUEUED)
        self.assertEqual(updated["parser_metadata"]["phase"], LIFECYCLE_STAGE_CHILD_ENQUEUED)

    async def test_emit_event_mirrors_child_non_terminal_events_onto_root_stream(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )

        await gateway.emit_event(child_job_id, {"job_id": child_job_id, "token": "hello"})
        await gateway.emit_event(child_job_id, {"result": "partial"})

        child_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(child_job_id)]]
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]

        self.assertIn({"job_id": child_job_id, "token": "hello"}, child_payloads)
        self.assertIn({"result": "partial"}, child_payloads)
        self.assertIn({"job_id": root_job_id, "token": "hello", "source_job_id": child_job_id}, root_payloads)
        self.assertIn({"result": "partial", "source_job_id": child_job_id}, root_payloads)

    async def test_child_completed_synthesizes_root_terminal_state_and_event(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
            parser_metadata_updates={"phase": LIFECYCLE_STAGE_CHILD_ENQUEUED},
        )

        await gateway.mark_job_completed(child_job_id, "final answer")

        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        self.assertEqual(child_job["status"], JOB_STATUS_COMPLETED)
        self.assertEqual(root_job["status"], JOB_STATUS_COMPLETED)
        self.assertEqual(root_job["result"], "final answer")
        self.assertEqual(root_job["child_job_id"], child_job_id)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_COMPLETED)
        self.assertEqual(root_job["parser_metadata"]["phase"], LIFECYCLE_STAGE_CHILD_COMPLETED)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)
        self.assertEqual(root_payloads[-1], {"done": True, "source_job_id": child_job_id})

    async def test_child_failed_synthesizes_root_failed_state(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )

        await gateway.mark_job_failed(child_job_id, "inference failed")

        root_job = await gateway.get_job(root_job_id)
        self.assertEqual(root_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(root_job["error"], "inference failed")
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_FAILED)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(root_payloads[-1], {"error": "inference failed", "done": True, "source_job_id": child_job_id})

    async def test_child_cancelled_synthesizes_root_cancelled_state(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )

        await gateway.mark_job_cancelled(child_job_id)

        root_job = await gateway.get_job(root_job_id)
        self.assertEqual(root_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_CANCELLED)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(root_payloads[-1], {"cancelled": True, "done": True, "source_job_id": child_job_id})

    async def test_stream_events_for_root_exits_on_synthesized_root_terminal_only(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )
        await gateway.emit_event(child_job_id, {"token": "hello"})
        await gateway.mark_job_completed(child_job_id, "final answer")

        payloads = [payload async for payload in gateway.stream_events(root_job_id)]
        mirrored_payloads = [payload for payload in payloads if payload.get("source_job_id") == child_job_id]
        self.assertIn({"token": "hello", "source_job_id": child_job_id}, mirrored_payloads)
        self.assertEqual(mirrored_payloads[-1], {"done": True, "source_job_id": child_job_id})
        self.assertEqual(len([payload for payload in mirrored_payloads if payload.get("done")]), 1)

    async def test_root_terminal_record_is_saved_before_root_done_event(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )

        original_save_job = gateway.save_job
        original_append_event = gateway._append_event
        call_log = []

        async def traced_save_job(job):
            call_log.append(("save_job", job["id"], job.get("status")))
            await original_save_job(job)

        async def traced_append_event(job_id, event):
            call_log.append(("append_event", job_id, bool(event.get("done"))))
            await original_append_event(job_id, event)

        gateway.save_job = traced_save_job
        gateway._append_event = traced_append_event

        await gateway.mark_job_completed(child_job_id, "final answer")

        root_save_index = next(
            index
            for index, entry in enumerate(call_log)
            if entry[0] == "save_job" and entry[1] == root_job_id and entry[2] == JOB_STATUS_COMPLETED
        )
        root_done_index = next(
            index
            for index, entry in enumerate(call_log)
            if entry[0] == "append_event" and entry[1] == root_job_id and entry[2] is True
        )
        self.assertLess(root_save_index, root_done_index)

    async def test_root_only_failure_before_child_enqueue_remains_unmirrored(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )

        await gateway.mark_job_failed(root_job_id, "parser failure")

        root_job = await gateway.get_job(root_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(root_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(root_payloads[-1], {"error": "parser failure", "done": True})
        self.assertEqual(len([payload for payload in root_payloads if payload.get("source_job_id")]), 0)

    async def test_non_parser_file_chat_jobs_remain_unmirrored(self):
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

        await gateway.emit_event(job_id, {"token": "hello"})
        await gateway.mark_job_completed(job_id, "final answer")

        payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(job_id)]]
        self.assertIn({"token": "hello"}, payloads)
        self.assertEqual(payloads[-1], {"done": True})

    async def test_deadline_exceeded_fallback_synthesizes_root_failed_state(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )
        child_job = await gateway.get_job(child_job_id)
        child_job.update(
            {
                "status": "running",
                "assigned_worker_id": "worker-1",
                "lease_until": 1,
                "deadline_at": 1,
            }
        )
        await gateway.save_job(child_job)
        await gateway.redis.zadd(gateway.ACTIVE_JOBS_ZSET, {child_job_id: 1})

        recovered = await gateway.requeue_stale_jobs()

        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(recovered, 0)
        self.assertEqual(child_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(child_job["error"], DEADLINE_EXCEEDED_ERROR)
        self.assertEqual(root_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_FAILED)
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)
        self.assertEqual(root_payloads[-1], {"error": DEADLINE_EXCEEDED_ERROR, "done": True, "source_job_id": child_job_id})

    async def test_retry_exhausted_fallback_synthesizes_root_failed_state(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )
        child_job = await gateway.get_job(child_job_id)
        child_job.update(
            {
                "status": "running",
                "assigned_worker_id": "worker-1",
                "lease_until": 1,
                "deadline_at": 9999999999,
                "retry_count": int(child_job.get("max_retries") or 0),
            }
        )
        await gateway.save_job(child_job)
        await gateway.redis.zadd(gateway.ACTIVE_JOBS_ZSET, {child_job_id: 1})

        recovered = await gateway.requeue_stale_jobs()

        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertEqual(recovered, 0)
        self.assertEqual(child_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(child_job["error"], GENERIC_CHAT_ERROR)
        self.assertEqual(root_job["status"], JOB_STATUS_FAILED)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_FAILED)
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)
        self.assertEqual(root_payloads[-1], {"error": GENERIC_CHAT_ERROR, "done": True, "source_job_id": child_job_id})

    async def test_root_cancel_cancels_linked_queued_child_and_synthesizes_root(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )

        cancelled = await gateway.cancel_job(root_job_id, username="alice")
        repeated = await gateway.cancel_job(root_job_id, username="alice")

        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertTrue(cancelled)
        self.assertFalse(repeated)
        self.assertEqual(child_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(root_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_CANCELLED)
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)
        self.assertEqual(root_payloads[-1], {"cancelled": True, "done": True, "source_job_id": child_job_id})

    async def test_root_cancel_cancels_linked_admitted_child_and_synthesizes_root(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        child_job_id, _ = await gateway.enqueue_child_job_once(
            root_job_id,
            prepared_llm_job={
                "job_kind": JOB_KIND_FILE_CHAT,
                "model_key": "demo-model",
                "model_name": "demo-model",
                "prompt": "grounded prompt",
                "history": [],
                "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                "staging_id": "staging-1",
            },
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        await gateway.save_job(root_job)
        await gateway.mark_job_waiting_on_child(
            root_job_id,
            child_job_id=child_job_id,
            lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
        )
        child_job = await gateway.get_job(child_job_id)
        child_job["status"] = "admitted"
        child_job["assigned_target_id"] = "cpu-target"
        await gateway.save_job(child_job)
        await gateway.redis.rpush(gateway.dispatch_queue_key(child_job["worker_pool"], "cpu-target"), child_job_id)

        cancelled = await gateway.cancel_job(root_job_id, username="alice")

        root_job = await gateway.get_job(root_job_id)
        child_job = await gateway.get_job(child_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        dispatch_queue = gateway.redis.lists[gateway.dispatch_queue_key(child_job["worker_pool"], "cpu-target")]
        self.assertTrue(cancelled)
        self.assertEqual(dispatch_queue, [])
        self.assertEqual(child_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(root_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(root_job["lifecycle_stage"], LIFECYCLE_STAGE_CHILD_CANCELLED)
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)
        self.assertEqual(root_payloads[-1], {"cancelled": True, "done": True, "source_job_id": child_job_id})

    async def test_enqueue_child_under_lock_aborts_when_root_cancel_requested(self):
        gateway = self.build_gateway()
        root_job_id = await gateway.enqueue_job(
            username="alice",
            model_key="demo-model",
            model_name="demo-model",
            prompt="summarize",
            history=[],
            job_kind=JOB_KIND_PARSE,
            workload_class=WORKLOAD_PARSE,
            staging_id="staging-1",
        )
        root_job = await gateway.get_job(root_job_id)
        root_job["status"] = "running"
        root_job["lifecycle_stage"] = LIFECYCLE_STAGE_PARSER_PREPARED
        await gateway.save_job(root_job)

        cancelled = await gateway.cancel_job(root_job_id, username="alice")
        root_job = await gateway.get_job(root_job_id)
        self.assertTrue(cancelled)
        self.assertTrue(root_job["cancel_requested"])

        with self.assertRaises(ParserChildEnqueueCancelled):
            await gateway.enqueue_child_job_once(
                root_job_id,
                prepared_llm_job={
                    "job_kind": JOB_KIND_FILE_CHAT,
                    "model_key": "demo-model",
                    "model_name": "demo-model",
                    "prompt": "grounded prompt",
                    "history": [],
                    "file_chat": {"files": [{"name": "note.txt", "size": 5}]},
                    "staging_id": "staging-1",
                },
            )

        self.assertIsNone(await gateway.get_job(gateway.derived_child_job_id(root_job_id)))
        await gateway.mark_job_cancelled(root_job_id)
        repeated = await gateway.cancel_job(root_job_id, username="alice")

        root_job = await gateway.get_job(root_job_id)
        root_payloads = [json.loads(fields["data"]) for _, fields in gateway.redis.streams[gateway.events_key(root_job_id)]]
        self.assertFalse(repeated)
        self.assertEqual(root_job["status"], JOB_STATUS_CANCELLED)
        self.assertEqual(len([payload for payload in root_payloads if payload.get("done")]), 1)

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

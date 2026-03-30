import asyncio
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
from starlette.datastructures import Headers

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

import app as app_module
import parser_stage
import worker as worker_module
from llm_gateway import JOB_KIND_PARSE, LIFECYCLE_STAGE_CHILD_ENQUEUED, LIFECYCLE_STAGE_PARSER_PREPARED, WORKLOAD_PARSE, WORKER_POOL_PARSER


class SharedStagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_staging_writes_safe_files_and_json_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            upload = UploadFile(
                filename="../../note.txt",
                file=io.BytesIO(b"hello"),
                headers=Headers({"content-type": "text/plain"}),
            )

            staged = await parser_stage.stage_uploads_to_shared_root([upload], staging_root=tmp, username="alice")

            self.assertIn("staging_id", staged)
            self.assertEqual(len(staged["files"]), 1)
            file_info = staged["files"][0]
            self.assertNotIn("/", file_info["safe_name"])
            self.assertNotIn("..", file_info["safe_name"])

            paths = parser_stage.shared_staging_paths(staged["staging_id"], staging_root=tmp)
            self.assertTrue((paths["raw_dir"] / file_info["safe_name"]).exists())
            self.assertTrue(paths["request_path"].exists())
            self.assertTrue(paths["parser_path"].exists())

            request_payload = json.loads(paths["request_path"].read_text(encoding="utf-8"))
            parser_payload = json.loads(paths["parser_path"].read_text(encoding="utf-8"))
            serialized = json.dumps(request_payload, ensure_ascii=False)
            self.assertIn("alice", serialized)
            self.assertNotIn("hello", serialized)
            self.assertNotIn(str(paths["raw_dir"]), serialized)
            self.assertEqual(request_payload["files"][0]["safe_name"], file_info["safe_name"])
            self.assertEqual(parser_payload["status"], "staged")
            self.assertFalse(parser_payload["raw_deleted"])

    async def test_enqueue_parser_job_uses_safe_queue_payload_only(self):
        gateway = type("Gateway", (), {})()
        gateway.enqueue_job = AsyncMock(return_value="parse-job-1")

        with patch.object(app_module.settings, "ENABLE_PARSER_STAGE", True):
            job_id = await app_module.enqueue_parser_job(
                gateway=gateway,
                username="alice",
                model_info={"key": "demo", "name": "demo"},
                message="Summarize",
                history=[{"role": "user", "content": "Earlier"}],
                staging_id="staging-1",
                staged_files=[
                    {
                        "name": "note.txt",
                        "safe_name": "abc123-note.txt",
                        "size": 5,
                        "content_type": "text/plain",
                    }
                ],
                requested_model="demo",
            )

        self.assertEqual(job_id, "parse-job-1")
        kwargs = gateway.enqueue_job.await_args.kwargs
        self.assertEqual(kwargs["job_kind"], JOB_KIND_PARSE)
        self.assertEqual(kwargs["workload_class"], WORKLOAD_PARSE)
        self.assertEqual(kwargs["staging_id"], "staging-1")
        serialized = json.dumps(kwargs["parser_metadata"], ensure_ascii=False)
        self.assertIn("abc123-note.txt", serialized)
        self.assertNotIn("/tmp", serialized)
        self.assertNotIn("hello", serialized)
        self.assertNotIn("path", serialized)


class SharedParserExtractionTests(unittest.TestCase):
    def test_extract_documents_from_shared_staging_dispatches_supported_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            uploads = [
                UploadFile(filename="a.txt", file=io.BytesIO(b"a"), headers=Headers({"content-type": "text/plain"})),
                UploadFile(
                    filename="b.docx",
                    file=io.BytesIO(b"b"),
                    headers=Headers({"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
                ),
                UploadFile(filename="c.pdf", file=io.BytesIO(b"c"), headers=Headers({"content-type": "application/pdf"})),
                UploadFile(filename="d.png", file=io.BytesIO(b"d"), headers=Headers({"content-type": "image/png"})),
            ]
            staged = asyncio.run(parser_stage.stage_uploads_to_shared_root(uploads, staging_root=tmp, username="alice"))

            with patch.object(parser_stage, "extract_text_from_txt", return_value="txt"), patch.object(
                parser_stage, "extract_text_from_docx", return_value="docx"
            ), patch.object(parser_stage, "extract_text_from_pdf", return_value="pdf"), patch.object(
                parser_stage, "extract_text_from_image", return_value="img"
            ):
                documents = parser_stage.extract_documents_from_shared_staging(staged["staging_id"], staging_root=tmp)

        self.assertEqual(
            documents,
            [
                {"name": "a.txt", "content": "txt"},
                {"name": "b.docx", "content": "docx"},
                {"name": "c.pdf", "content": "pdf"},
                {"name": "d.png", "content": "img"},
            ],
        )


class ParserWorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_parser_worker_enqueues_child_and_keeps_root_non_terminal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER
        ), patch.object(worker_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            worker_module.settings, "PARSER_STAGING_ROOT", tmp
        ), patch.object(
            worker_module.settings, "PARSER_JOB_TIMEOUT_SECONDS", 5
        ):
            uploads = [
                UploadFile(
                    filename="a.txt",
                    file=io.BytesIO(b"A" * parser_stage.MAX_DOCUMENT_CHARS),
                    headers=Headers({"content-type": "text/plain"}),
                ),
                UploadFile(
                    filename="b.txt",
                    file=io.BytesIO(b"B" * 100),
                    headers=Headers({"content-type": "text/plain"}),
                ),
            ]
            staged = await parser_stage.stage_uploads_to_shared_root(uploads, staging_root=tmp, username="alice")
            worker = worker_module.LLMWorker()
            worker.gateway = type("Gateway", (), {})()
            worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
            worker.gateway.get_job = AsyncMock(
                return_value={
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                    "prompt": "Summarize",
                    "history": [{"role": "user", "content": "Earlier"}],
                    "model_key": "demo",
                    "model_name": "demo",
                    "parser_metadata": {"phase": "staged", "files": staged["files"]},
                    "status": "running",
                }
            )
            worker.gateway.get_linked_child_job_id = AsyncMock(return_value=None)
            worker.gateway.enqueue_child_job_once = AsyncMock(return_value=("child-job-1", True))
            worker.gateway.save_job = AsyncMock(return_value=None)
            worker.gateway.mark_job_waiting_on_child = AsyncMock(return_value=None)
            worker.gateway.mark_job_completed = AsyncMock(return_value=None)
            worker.gateway.mark_job_failed = AsyncMock(return_value=None)
            worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

            await worker.process_job(
                {
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                    "prompt": "Summarize",
                    "history": [{"role": "user", "content": "Earlier"}],
                    "model_key": "demo",
                    "model_name": "demo",
                    "parser_metadata": {"phase": "staged", "files": staged["files"]},
                }
            )
            worker.gateway.mark_job_failed.assert_not_awaited()
            worker.gateway.mark_job_cancelled.assert_not_awaited()
            worker.gateway.mark_job_completed.assert_not_awaited()
            worker.gateway.enqueue_child_job_once.assert_awaited_once()
            worker.gateway.mark_job_waiting_on_child.assert_awaited_once()
            self.assertEqual(
                worker.gateway.mark_job_waiting_on_child.await_args.kwargs["lifecycle_stage"],
                LIFECYCLE_STAGE_CHILD_ENQUEUED,
            )
            self.assertEqual(worker.gateway.mark_job_waiting_on_child.await_args.kwargs["child_job_id"], "child-job-1")

            saved_job = worker.gateway.save_job.await_args.args[0]
            self.assertEqual(saved_job["parser_metadata"]["phase"], LIFECYCLE_STAGE_PARSER_PREPARED)
            self.assertFalse(saved_job["parser_metadata"]["raw_deleted"])
            self.assertEqual(saved_job["parser_metadata"]["artifact"], "meta/parser.json")
            self.assertEqual(saved_job["lifecycle_stage"], LIFECYCLE_STAGE_PARSER_PREPARED)
            self.assertLess(
                saved_job["parser_metadata"]["trimmed_doc_chars"],
                saved_job["parser_metadata"]["original_doc_chars"],
            )

            paths = parser_stage.shared_staging_paths(staged["staging_id"], staging_root=tmp)
            self.assertFalse(paths["raw_dir"].exists())
            self.assertTrue(paths["request_path"].exists())
            parser_payload = json.loads(paths["parser_path"].read_text(encoding="utf-8"))
            self.assertEqual(parser_payload["status"], LIFECYCLE_STAGE_CHILD_ENQUEUED)
            self.assertTrue(parser_payload["raw_deleted"])
            self.assertEqual(parser_payload["child_job_id"], "child-job-1")
            self.assertEqual(parser_payload["prepared_llm_job"]["job_kind"], "file_chat")
            self.assertIn("[Документ 1: a.txt]", parser_payload["prepared_llm_job"]["prompt"])
            self.assertIn(parser_stage.DOCUMENT_TRUNCATION_MARKER, parser_payload["prepared_llm_job"]["prompt"])

    async def test_parser_worker_reuses_existing_child_without_duplicate_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER
        ), patch.object(worker_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            worker_module.settings, "PARSER_STAGING_ROOT", tmp
        ):
            upload = UploadFile(
                filename="a.txt",
                file=io.BytesIO(b"A"),
                headers=Headers({"content-type": "text/plain"}),
            )
            staged = await parser_stage.stage_uploads_to_shared_root([upload], staging_root=tmp, username="alice")
            worker = worker_module.LLMWorker()
            worker.gateway = type("Gateway", (), {})()
            worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
            worker.gateway.get_job = AsyncMock(
                return_value={
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                    "parser_metadata": {"phase": LIFECYCLE_STAGE_PARSER_PREPARED, "files": staged["files"]},
                    "status": "running",
                }
            )
            worker.gateway.get_linked_child_job_id = AsyncMock(return_value="child-job-1")
            worker.gateway.enqueue_child_job_once = AsyncMock(return_value=("child-job-1", False))
            worker.gateway.mark_job_waiting_on_child = AsyncMock(return_value=None)
            worker.gateway.mark_job_failed = AsyncMock(return_value=None)
            worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

            await worker.process_job(
                {
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                }
            )

            worker.gateway.enqueue_child_job_once.assert_not_awaited()
            worker.gateway.mark_job_waiting_on_child.assert_awaited_once()
            parser_payload = json.loads(
                parser_stage.shared_staging_paths(staged["staging_id"], staging_root=tmp)["parser_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(parser_payload["status"], LIFECYCLE_STAGE_CHILD_ENQUEUED)
            self.assertEqual(parser_payload["child_job_id"], "child-job-1")

    async def test_parser_artifact_preparation_failure_is_distinct(self):
        with patch.object(worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER), patch.object(
            worker_module.settings, "ENABLE_PARSER_STAGE", True
        ), patch.object(worker_module, "prepare_parser_job_artifacts", side_effect=RuntimeError("parse boom")):
            worker = worker_module.LLMWorker()
            worker.gateway = type("Gateway", (), {})()
            worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
            worker.gateway.get_job = AsyncMock(
                return_value={
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": "staging-1",
                    "prompt": "Summarize",
                    "history": [],
                    "model_key": "demo",
                    "model_name": "demo",
                }
            )
            worker.gateway.get_linked_child_job_id = AsyncMock(return_value=None)
            worker.gateway.mark_job_failed = AsyncMock(return_value=None)
            worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

            await worker.process_job(
                {
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": "staging-1",
                }
            )

            worker.gateway.mark_job_failed.assert_awaited_once()
            self.assertIn("Parser artifact preparation failed", worker.gateway.mark_job_failed.await_args.args[1])

    async def test_parser_child_enqueue_failure_is_distinct(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            worker_module.settings, "WORKER_POOL", WORKER_POOL_PARSER
        ), patch.object(worker_module.settings, "ENABLE_PARSER_STAGE", True), patch.object(
            worker_module.settings, "PARSER_STAGING_ROOT", tmp
        ):
            upload = UploadFile(
                filename="a.txt",
                file=io.BytesIO(b"A"),
                headers=Headers({"content-type": "text/plain"}),
            )
            staged = await parser_stage.stage_uploads_to_shared_root([upload], staging_root=tmp, username="alice")
            worker = worker_module.LLMWorker()
            worker.gateway = type("Gateway", (), {})()
            worker.gateway.is_cancel_requested = AsyncMock(return_value=False)
            worker.gateway.get_job = AsyncMock(
                return_value={
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                    "prompt": "Summarize",
                    "history": [],
                    "model_key": "demo",
                    "model_name": "demo",
                }
            )
            worker.gateway.get_linked_child_job_id = AsyncMock(return_value=None)
            worker.gateway.enqueue_child_job_once = AsyncMock(side_effect=RuntimeError("queue down"))
            worker.gateway.save_job = AsyncMock(return_value=None)
            worker.gateway.mark_job_failed = AsyncMock(return_value=None)
            worker.gateway.mark_job_cancelled = AsyncMock(return_value=None)

            await worker.process_job(
                {
                    "id": "parse-job-1",
                    "username": "alice",
                    "job_kind": JOB_KIND_PARSE,
                    "workload_class": WORKLOAD_PARSE,
                    "staging_id": staged["staging_id"],
                    "prompt": "Summarize",
                    "history": [],
                    "model_key": "demo",
                    "model_name": "demo",
                }
            )

            worker.gateway.mark_job_failed.assert_awaited_once()
            self.assertIn("Parser child enqueue failed", worker.gateway.mark_job_failed.await_args.args[1])


if __name__ == "__main__":
    unittest.main()

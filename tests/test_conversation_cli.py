import io
import json
import os
import tempfile
import unittest
from contextlib import asynccontextmanager

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")

from persistence.conversation_cli import main
from persistence.conversation_store import ConversationStore
from persistence.database import close_conversation_persistence, init_conversation_persistence


class FakeSourceStore:
    def __init__(self, histories: dict[str, list[dict[str, object]]]):
        self.histories = histories

    async def list_threads(self, username: str) -> list[dict[str, object]]:
        return [{"thread_id": thread_id} for thread_id in self.histories.keys()]

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, object]]:
        return list(self.histories.get(thread_id or "default", []))


class ConversationCliTests(unittest.TestCase):
    def test_bootstrap_schema_prints_stable_json_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = main(
                [
                    "bootstrap-schema",
                    "--database-url",
                    f"sqlite+pysqlite:///{tmpdir}/bootstrap-cli.db",
                ],
                stdout=stdout,
                stderr=stderr,
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["operation"], "bootstrap-schema")
            self.assertEqual(payload["table_count"], 2)
            self.assertEqual(
                payload["tables"],
                ["conversation_messages", "conversation_threads"],
            )

    def test_migrate_thread_writes_snapshot_and_prints_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = FakeSourceStore(
                {
                    "default": [
                        {"role": "user", "content": "Привет"},
                        {"role": "assistant", "content": "Здравствуйте"},
                    ]
                }
            )
            runtime = init_conversation_persistence(
                f"sqlite+pysqlite:///{tmpdir}/migrate-thread-cli.db",
                create_schema=True,
            )
            close_conversation_persistence(runtime)
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = main(
                [
                    "migrate-thread",
                    "--redis-url",
                    "redis://unused",
                    "--database-url",
                    f"sqlite+pysqlite:///{tmpdir}/migrate-thread-cli.db",
                    "--username",
                    "alice",
                    "--thread-id",
                    "default",
                ],
                stdout=stdout,
                stderr=stderr,
                source_context_factory=self._source_context_factory(source),
            )

            verify_runtime = init_conversation_persistence(
                f"sqlite+pysqlite:///{tmpdir}/migrate-thread-cli.db",
                create_schema=False,
            )
            try:
                payload = json.loads(stdout.getvalue())
                messages = ConversationStore(verify_runtime.session_factory).get_messages("alice", "default")
                self.assertEqual(exit_code, 0)
                self.assertEqual(stderr.getvalue(), "")
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["operation"], "migrate-thread")
                self.assertTrue(payload["migrated"])
                self.assertEqual(payload["message_count"], 2)
                self.assertFalse(payload["skipped_empty"])
                self.assertEqual([item.content for item in messages], ["Привет", "Здравствуйте"])
            finally:
                close_conversation_persistence(verify_runtime)

    def test_migrate_user_prints_controlled_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = FakeSourceStore(
                {
                    "default": [{"role": "user", "content": "A"}],
                    "other": [{"role": "assistant", "content": "B"}],
                    "empty": [],
                }
            )
            runtime = init_conversation_persistence(
                f"sqlite+pysqlite:///{tmpdir}/migrate-user-cli.db",
                create_schema=True,
            )
            close_conversation_persistence(runtime)
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = main(
                [
                    "migrate-user",
                    "--redis-url",
                    "redis://unused",
                    "--database-url",
                    f"sqlite+pysqlite:///{tmpdir}/migrate-user-cli.db",
                    "--username",
                    "alice",
                ],
                stdout=stdout,
                stderr=stderr,
                source_context_factory=self._source_context_factory(source),
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["operation"], "migrate-user")
            self.assertEqual(payload["migrated_thread_count"], 2)
            self.assertEqual(payload["migrated_message_count"], 2)
            self.assertEqual(payload["skipped_empty_threads"], ["empty"])

    def test_compare_user_prints_counted_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = FakeSourceStore(
                {
                    "matched": [{"role": "user", "content": "A"}],
                    "source-only": [{"role": "user", "content": "SRC"}],
                    "mismatch": [{"role": "user", "content": "SRC"}],
                    "empty": [],
                }
            )
            runtime = init_conversation_persistence(
                f"sqlite+pysqlite:///{tmpdir}/compare-user-cli.db",
                create_schema=True,
            )
            try:
                store = ConversationStore(runtime.session_factory)
                store.import_thread_snapshot("alice", "matched", [{"role": "user", "content": "A"}])
                store.import_thread_snapshot("alice", "db-only", [{"role": "user", "content": "DB"}])
                store.import_thread_snapshot("alice", "mismatch", [{"role": "user", "content": "DB"}])
            finally:
                close_conversation_persistence(runtime)

            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = main(
                [
                    "compare-user",
                    "--redis-url",
                    "redis://unused",
                    "--database-url",
                    f"sqlite+pysqlite:///{tmpdir}/compare-user-cli.db",
                    "--username",
                    "alice",
                ],
                stdout=stdout,
                stderr=stderr,
                source_context_factory=self._source_context_factory(source),
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["operation"], "compare-user")
            self.assertEqual(payload["matched_count"], 1)
            self.assertEqual(payload["missing_in_db_count"], 1)
            self.assertEqual(payload["missing_in_source_count"], 1)
            self.assertEqual(payload["content_mismatch_count"], 1)
            self.assertEqual(payload["empty_count"], 1)
            self.assertEqual(payload["matched_threads"], ["matched"])
            self.assertEqual(payload["missing_in_db_threads"], ["source-only"])
            self.assertEqual(payload["missing_in_source_threads"], ["db-only"])
            self.assertEqual(payload["content_mismatch_threads"], ["mismatch"])
            self.assertEqual(payload["empty_threads"], ["empty"])

    @staticmethod
    def _source_context_factory(source: FakeSourceStore):
        @asynccontextmanager
        async def _factory(redis_url: str):
            del redis_url
            yield source

        return _factory


if __name__ == "__main__":
    unittest.main()

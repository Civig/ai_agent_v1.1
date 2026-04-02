from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional, Sequence

from sqlalchemy import inspect

from .conversation_migrator import migrate_all_threads_for_user, migrate_thread_for_user
from .conversation_parity import compare_all_threads_for_user, compare_thread_for_user
from .conversation_store import ConversationStore
from .database import close_conversation_persistence, init_conversation_persistence

try:
    import redis.asyncio as redis_async
except ModuleNotFoundError:  # pragma: no cover
    redis_async = None


DEFAULT_CHAT_THREAD_ID = "default"
DEFAULT_MAX_HISTORY = 100


class ConversationUtilityError(RuntimeError):
    pass


class ConversationUtilityArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ConversationUtilityError(message)


class ReadOnlyRedisConversationHistorySource:
    def __init__(self, redis_url: str, *, max_history: int = DEFAULT_MAX_HISTORY):
        self.redis_url = redis_url
        self.max_history = max_history
        self.redis: Any = None

    async def connect(self) -> None:
        if redis_async is None:
            raise ConversationUtilityError("redis package is required for offline conversation persistence utility")
        self.redis = redis_async.from_url(self.redis_url, decode_responses=True)
        await self.redis.ping()

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None

    async def get_history(self, username: str, *, thread_id: str | None = None) -> list[dict[str, Any]]:
        normalized_username = _require_non_empty(username, "username")
        normalized_thread_id = _normalize_thread_id(thread_id)
        candidate_keys = [self.history_key(normalized_username, normalized_thread_id)]
        if normalized_thread_id == DEFAULT_CHAT_THREAD_ID:
            candidate_keys.append(self.legacy_history_key(normalized_username))

        if self.redis is None:
            raise ConversationUtilityError("Redis source is not connected")

        for key in candidate_keys:
            entries = await self.redis.lrange(key, 0, -1)
            if entries:
                return self._decode_history_entries(entries)
        return []

    async def list_threads(self, username: str) -> list[dict[str, Any]]:
        normalized_username = _require_non_empty(username, "username")
        if self.redis is None:
            raise ConversationUtilityError("Redis source is not connected")

        registry_scores = await self._load_registry_scores(normalized_username)
        thread_ids = set(registry_scores.keys())

        async for key in self.redis.scan_iter(match=f"{self._history_key_prefix(normalized_username)}*"):
            thread_id = self._extract_thread_id_from_history_key(normalized_username, key)
            if thread_id:
                thread_ids.add(thread_id)

        if await self.redis.exists(self.legacy_history_key(normalized_username)):
            thread_ids.add(DEFAULT_CHAT_THREAD_ID)

        summaries: list[dict[str, Any]] = []
        for thread_id in thread_ids:
            history = await self.get_history(normalized_username, thread_id=thread_id)
            summaries.append(
                {
                    "thread_id": thread_id,
                    "updated_at": registry_scores.get(
                        thread_id,
                        await self._latest_history_timestamp(normalized_username, thread_id),
                    ),
                    "message_count": len(history),
                }
            )

        summaries.sort(key=lambda item: (-int(item["updated_at"]), str(item["thread_id"])))
        return summaries

    def legacy_history_key(self, username: str) -> str:
        return f"chat:{username}"

    def thread_registry_key(self, username: str) -> str:
        return f"chat:{username}:threads"

    def history_key(self, username: str, thread_id: str | None = None) -> str:
        return f"chat:{username}:{_normalize_thread_id(thread_id)}"

    def _history_key_prefix(self, username: str) -> str:
        return f"chat:{username}:"

    def _extract_thread_id_from_history_key(self, username: str, key: str) -> Optional[str]:
        normalized_key = str(key)
        prefix = self._history_key_prefix(username)
        if not normalized_key.startswith(prefix):
            return None
        thread_id = normalized_key[len(prefix) :].strip()
        if not thread_id or thread_id == "threads":
            return None
        return thread_id

    async def _load_registry_scores(self, username: str) -> dict[str, int]:
        if self.redis is None:
            raise ConversationUtilityError("Redis source is not connected")
        members = await self.redis.zrevrange(self.thread_registry_key(username), 0, -1, withscores=True)
        scores: dict[str, int] = {}
        for member, score in members:
            scores[str(member)] = int(score)
        return scores

    async def _latest_history_timestamp(self, username: str, thread_id: str) -> int:
        if self.redis is None:
            raise ConversationUtilityError("Redis source is not connected")

        candidate_keys = [self.history_key(username, thread_id)]
        if _normalize_thread_id(thread_id) == DEFAULT_CHAT_THREAD_ID:
            candidate_keys.append(self.legacy_history_key(username))

        for key in candidate_keys:
            entries = await self.redis.lrange(key, -1, -1)
            if not entries:
                continue
            try:
                payload = json.loads(entries[-1])
            except json.JSONDecodeError:
                continue
            return _safe_int(payload.get("created_at"))
        return 0

    def _decode_history_entries(self, entries: Sequence[str]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for entry in entries:
            try:
                payload = json.loads(entry)
            except json.JSONDecodeError:
                continue
            role = payload.get("role")
            content = payload.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                history.append({"role": role, "content": content})
        return history[-self.max_history :]


def build_parser() -> argparse.ArgumentParser:
    parser = ConversationUtilityArgumentParser(
        prog="python -m persistence.conversation_cli",
        description="Offline utility for explicit conversation persistence operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap-schema")
    bootstrap_parser.add_argument("--database-url", required=True)

    migrate_thread_parser = subparsers.add_parser("migrate-thread")
    migrate_thread_parser.add_argument("--redis-url", required=True)
    migrate_thread_parser.add_argument("--database-url", required=True)
    migrate_thread_parser.add_argument("--username", required=True)
    migrate_thread_parser.add_argument("--thread-id", required=True)

    migrate_user_parser = subparsers.add_parser("migrate-user")
    migrate_user_parser.add_argument("--redis-url", required=True)
    migrate_user_parser.add_argument("--database-url", required=True)
    migrate_user_parser.add_argument("--username", required=True)

    compare_thread_parser = subparsers.add_parser("compare-thread")
    compare_thread_parser.add_argument("--redis-url", required=True)
    compare_thread_parser.add_argument("--database-url", required=True)
    compare_thread_parser.add_argument("--username", required=True)
    compare_thread_parser.add_argument("--thread-id", required=True)

    compare_user_parser = subparsers.add_parser("compare-user")
    compare_user_parser.add_argument("--redis-url", required=True)
    compare_user_parser.add_argument("--database-url", required=True)
    compare_user_parser.add_argument("--username", required=True)

    return parser


@asynccontextmanager
async def open_read_only_redis_source(
    redis_url: str,
) -> AsyncIterator[ReadOnlyRedisConversationHistorySource]:
    source = ReadOnlyRedisConversationHistorySource(redis_url)
    await source.connect()
    try:
        yield source
    finally:
        await source.close()


async def run_cli_command(
    args: argparse.Namespace,
    *,
    source_context_factory: Callable[[str], AsyncIterator[Any]] = open_read_only_redis_source,
) -> dict[str, Any]:
    command = str(args.command)
    if command == "bootstrap-schema":
        runtime = init_conversation_persistence(args.database_url, create_schema=True)
        try:
            table_names = sorted(inspect(runtime.engine).get_table_names())
            return {
                "ok": True,
                "operation": command,
                "table_count": len(table_names),
                "tables": table_names,
            }
        finally:
            close_conversation_persistence(runtime)

    runtime = init_conversation_persistence(args.database_url, create_schema=False)
    try:
        db_store = ConversationStore(runtime.session_factory)
        async with source_context_factory(args.redis_url) as source_store:
            if command == "migrate-thread":
                result = await migrate_thread_for_user(source_store, db_store, args.username, args.thread_id)
                return {
                    "ok": True,
                    "operation": command,
                    "username": args.username,
                    "thread_id": result.thread_id,
                    "migrated": result.migrated,
                    "message_count": result.message_count,
                    "skipped_empty": result.skipped_empty,
                }

            if command == "migrate-user":
                result = await migrate_all_threads_for_user(source_store, db_store, args.username)
                return {
                    "ok": True,
                    "operation": command,
                    "username": result.username,
                    "migrated_thread_count": result.migrated_thread_count,
                    "migrated_message_count": result.migrated_message_count,
                    "skipped_empty_threads": list(result.skipped_empty_threads),
                }

            if command == "compare-thread":
                result = await compare_thread_for_user(source_store, db_store, args.username, args.thread_id)
                return {
                    "ok": True,
                    "operation": command,
                    "username": args.username,
                    "thread_id": result.thread_id,
                    "status": result.status,
                    "source_message_count": result.source_message_count,
                    "db_message_count": result.db_message_count,
                }

            if command == "compare-user":
                result = await compare_all_threads_for_user(source_store, db_store, args.username)
                return {
                    "ok": True,
                    "operation": command,
                    "username": result.username,
                    "matched_count": len(result.matched_threads),
                    "missing_in_db_count": len(result.missing_in_db_threads),
                    "missing_in_source_count": len(result.missing_in_source_threads),
                    "content_mismatch_count": len(result.content_mismatch_threads),
                    "empty_count": len(result.empty_threads),
                    "matched_threads": list(result.matched_threads),
                    "missing_in_db_threads": list(result.missing_in_db_threads),
                    "missing_in_source_threads": list(result.missing_in_source_threads),
                    "content_mismatch_threads": list(result.content_mismatch_threads),
                    "empty_threads": list(result.empty_threads),
                }
    finally:
        close_conversation_persistence(runtime)

    raise ConversationUtilityError(f"unsupported command: {command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: Any = None,
    stderr: Any = None,
    source_context_factory: Callable[[str], AsyncIterator[Any]] = open_read_only_redis_source,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()

    parsed_args: argparse.Namespace | None = None
    try:
        parsed_args = parser.parse_args(argv)
        payload = asyncio.run(
            run_cli_command(parsed_args, source_context_factory=source_context_factory)
        )
        _write_json(stdout, payload)
        return 0
    except (ConversationUtilityError, ValueError) as exc:
        _write_json(
            stderr,
            {
                "ok": False,
                "operation": getattr(parsed_args, "command", None),
                "error": str(exc),
            },
        )
        return 1
    except Exception as exc:  # pragma: no cover
        _write_json(
            stderr,
            {
                "ok": False,
                "operation": getattr(parsed_args, "command", None),
                "error": str(exc),
            },
        )
        return 1


def _write_json(stream: Any, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    stream.write("\n")


def _normalize_thread_id(thread_id: str | None) -> str:
    normalized = str(thread_id or "").strip()
    return normalized or DEFAULT_CHAT_THREAD_ID


def _require_non_empty(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

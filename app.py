import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import time
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

import bleach
import markdown as md
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from prometheus_client import Counter
from pydantic import BaseModel

from auth_kerberos import (
    AUTH_SOURCE_LOCAL_ADMIN,
    AUTH_SOURCE_PASSWORD,
    AUTH_SOURCE_SSO,
    create_access_token,
    enrich_identity_session_fields,
    extract_bearer_token,
    get_allowed_models_for_user,
    get_current_user,
    get_current_user_required,
    is_token_revoked,
    kerberos_auth,
    normalize_username,
    revoke_token,
    settings,
)
from dashboard_telemetry import (
    HISTORY_RANGE_SECONDS,
    build_dashboard_event,
    build_dashboard_events,
    build_dashboard_history_payload,
    build_dashboard_live_sample,
    normalize_history_range,
    sanitize_dashboard_live_sample,
)
from llm_gateway import (
    AsyncChatStore,
    AsyncRateLimiter,
    classify_observability_error,
    DEFAULT_CHAT_THREAD_ID,
    ERROR_TYPE_INTERNAL,
    ERROR_TYPE_NONE,
    ERROR_TYPE_PARSE,
    ERROR_TYPE_VALIDATION,
    JOB_KIND_FILE_CHAT,
    JOB_KIND_PARSE,
    LLMGateway,
    WORKLOAD_CHAT,
    WORKLOAD_PARSE,
    apply_history_budget,
    approximate_token_count,
    elapsed_ms,
)
from local_admin_security import (
    LOCAL_ADMIN_AUTH_SOURCE,
    LOCAL_ADMIN_STATE_REDIS_KEY,
    build_local_admin_password_hash,
    build_local_admin_state_revision,
    verify_local_admin_password,
)
import parser_stage
from persistence import (
    close_conversation_persistence_runtime,
    open_conversation_persistence_runtime,
)
from persistence.conversation_parity import (
    PARITY_EMPTY_THREAD,
    PARITY_MATCHED,
    compare_history_snapshot_to_messages,
    compare_history_snapshot_to_store,
)
from persistence.conversation_write_coordinator import (
    RedisConversationWriteCoordinator,
    create_conversation_write_coordinator,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GENERIC_AUTH_ERROR = "Ошибка аутентификации. Попробуйте снова позже."
CPU_LIGHTWEIGHT_MODEL_MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024
LOGIN_RATE_LIMIT_ERROR = "Слишком много попыток входа. Попробуйте позже."
AUTH_BACKEND_UNAVAILABLE_ERROR = "Сервис аутентификации временно недоступен."
NO_LLM_MODELS_AVAILABLE_ERROR = "No LLM models available"
LLM_MODELS_UNAVAILABLE_DESCRIPTION = "LLM runtime unavailable"
MAX_UPLOAD_FILE_SIZE_BYTES = parser_stage.MAX_UPLOAD_FILE_SIZE_BYTES
MAX_UPLOAD_TOTAL_SIZE_BYTES = parser_stage.MAX_UPLOAD_TOTAL_SIZE_BYTES
MAX_UPLOAD_FILES = parser_stage.MAX_UPLOAD_FILES
GENERIC_UPLOAD_CONTENT_TYPES = parser_stage.GENERIC_UPLOAD_CONTENT_TYPES
ALLOWED_UPLOAD_MIME_TYPES = parser_stage.ALLOWED_UPLOAD_MIME_TYPES
MAX_DOCUMENT_CHARS = parser_stage.MAX_DOCUMENT_CHARS
MAX_PARSED_DOCUMENT_CHARS = parser_stage.MAX_PARSED_DOCUMENT_CHARS
MAX_PDF_PAGES = parser_stage.MAX_PDF_PAGES
IMAGE_OCR_MAX_DIMENSION = parser_stage.IMAGE_OCR_MAX_DIMENSION
IMAGE_OCR_TIMEOUT_SECONDS = parser_stage.IMAGE_OCR_TIMEOUT_SECONDS
DOCUMENT_TRUNCATION_MARKER = "[DOCUMENT_TRUNCATED]"
UPLOAD_UNSUPPORTED_TYPE_ERROR = parser_stage.UPLOAD_UNSUPPORTED_TYPE_ERROR
DOCUMENT_NO_INFORMATION_RESPONSE = parser_stage.DOCUMENT_NO_INFORMATION_RESPONSE
DOCUMENT_UNCLEAR_REQUEST_RESPONSE = (
    "Я вижу, что вы загрузили документ. Хотите, чтобы я:\n"
    "- сделал краткое содержание\n"
    "- извлёк ключевые данные\n"
    "- нашёл важные моменты?"
)
DOCUMENT_RETRY_PATTERNS = (
    "не имею доступа к файлам",
    "не могу прочитать файл",
    "не могу открыть файл",
    "не имею доступа к документам",
    "у меня нет доступа к файлам",
    "у меня нет доступа к документам",
    "не вижу содержимое файла",
    "не вижу содержимое документа",
    "загрузите файл",
    "прикрепите файл",
)
DOCUMENT_NO_INFO_PATTERNS = (
    "не указан",
    "не указана",
    "не указано",
    "не указаны",
    "нет даты",
    "нет данных",
    "нет сведений",
    "не упоминается",
    "не содержится",
    "не содержит информации",
    "отсутствует",
    "отсутствуют",
    "нет информации",
    "не представлена",
    "не представлен",
)
RESERVED_AUTH_PROXY_HEADERS = frozenset(
    {
        "x-authenticated-user",
        "x-authenticated-principal",
        "x-authenticated-email",
        "x-authenticated-name",
        "x-authenticated-groups",
    }
)
ADMIN_DASHBOARD_REFRESH_INTERVAL_MS = 8000
LOCAL_ADMIN_ACCESS_COOKIE_NAME = "local_admin_access_token"
LOCAL_ADMIN_CSRF_COOKIE_NAME = "local_admin_csrf_token"
LOCAL_ADMIN_ACCESS_TOKEN_TYPE = "local_admin_access"
LOCAL_ADMIN_LOGIN_PATH = "/admin/local/login"
LOCAL_ADMIN_ROTATE_PATH = "/admin/local/rotate-password"
LOCAL_ADMIN_LOGOUT_PATH = "/admin/local/logout"
LOCAL_ADMIN_ROTATION_REQUIRED_ERROR = "Для break-glass admin требуется обязательная смена пароля."
LOCAL_ADMIN_NOT_CONFIGURED_ERROR = "Local break-glass admin is not configured."
LOCAL_ADMIN_AUTH_ERROR = "Неверные учётные данные local admin."

sanitize_upload_filename = parser_stage.sanitize_upload_filename
detect_extension = parser_stage.detect_extension
normalize_upload_content_type = parser_stage.normalize_upload_content_type
upload_content_type_is_allowed = parser_stage.upload_content_type_is_allowed
log_upload_rejection = parser_stage.log_upload_rejection
extract_text_from_txt = parser_stage.extract_text_from_txt
extract_text_from_docx = parser_stage.extract_text_from_docx
extract_text_from_pdf = parser_stage.extract_text_from_pdf
extract_text_from_image = parser_stage.extract_text_from_image
parse_uploaded_file = parser_stage.parse_uploaded_file
apply_document_budget = parser_stage.apply_document_budget
build_document_prompt = parser_stage.build_document_prompt
build_retry_document_prompt = parser_stage.build_retry_document_prompt
extract_documents_from_staging = parser_stage.extract_documents_from_staging


class PromptRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    thread_id: Optional[str] = None


class ThreadScopedRequest(BaseModel):
    thread_id: Optional[str] = None


class ThreadDeleteRequest(BaseModel):
    active_thread_id: Optional[str] = None


class MarkdownRequest(BaseModel):
    text: str


class ModelSwitchRequest(BaseModel):
    model: str


def filter_prompt_injection(prompt: str) -> str:
    forbidden_patterns = [
        r"(?i)ignore previous instructions",
        r"(?i)act as ",
        r"(?i)system: ",
        r"(?i)you are now ",
        r"(?i)jailbreak",
        r"(?i)prompt injection",
        r"(?i)simulate ",
        r"(?i)execute ",
        r"(?i)os\.system",
        r"(?i)import os",
        r"(?i)open\(.*\)",
        r"(?i)eval\(.*\)",
        r"(?i)base64",
        r"(?i)token:",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, prompt):
            return "[SECURITY WARNING: potentially unsafe input removed]"
    return prompt


def render_markdown(text: str) -> str:
    if not text:
        return ""

    html = md.markdown(text, extensions=["extra"])
    allowed_tags = [
        "p", "br", "strong", "em", "u", "s", "strike",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "blockquote", "pre", "code", "a",
        "table", "thead", "tbody", "tr", "th", "td",
    ]
    allowed_attributes = {"a": ["href", "title", "rel", "target"], "code": ["class"], "pre": ["class"]}
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attributes, strip=True)


def normalize_chat_thread_id(thread_id: Optional[str]) -> str:
    normalized = thread_id.strip() if isinstance(thread_id, str) else ""
    return normalized or DEFAULT_CHAT_THREAD_ID


def serialize_thread_summary(thread: dict[str, Any]) -> dict[str, Any]:
    updated_at_seconds = max(0, int(thread.get("updated_at") or 0))
    return {
        "id": normalize_chat_thread_id(thread.get("thread_id")),
        "title": (thread.get("title") or "Новый чат").strip() or "Новый чат",
        "updatedAt": updated_at_seconds * 1000,
        "messageCount": max(0, int(thread.get("message_count") or 0)),
    }


def build_conversation_writer(app_state: Any) -> RedisConversationWriteCoordinator:
    return create_conversation_write_coordinator(
        app_state.chat_store,
        db_store=getattr(app_state, "conversation_db_store", None),
        dual_write_enabled=settings.PERSISTENT_DB_DUAL_WRITE_CONVERSATION,
        logger=logger,
    )


async def load_thread_summaries(
    chat_store: AsyncChatStore,
    username: str,
    *,
    conversation_writer: Optional[RedisConversationWriteCoordinator] = None,
) -> list[dict[str, Any]]:
    threads = [serialize_thread_summary(thread) for thread in await chat_store.list_threads(username)]
    if threads:
        return threads

    if conversation_writer is None:
        await chat_store.create_thread(username, thread_id=DEFAULT_CHAT_THREAD_ID)
    else:
        await conversation_writer.ensure_thread(username, thread_id=DEFAULT_CHAT_THREAD_ID)
    return [serialize_thread_summary(thread) for thread in await chat_store.list_threads(username)]


def resolve_active_thread_id(thread_id: Optional[str], threads: list[dict[str, Any]]) -> str:
    requested_thread_id = normalize_chat_thread_id(thread_id)
    known_thread_ids = {thread["id"] for thread in threads}
    if requested_thread_id in known_thread_ids:
        return requested_thread_id
    if threads:
        return threads[0]["id"]
    return DEFAULT_CHAT_THREAD_ID


def find_thread_summary(threads: list[dict[str, Any]], thread_id: Optional[str]) -> Optional[dict[str, Any]]:
    normalized_thread_id = normalize_chat_thread_id(thread_id)
    for thread in threads:
        if thread["id"] == normalized_thread_id:
            return thread
    return None


def response_requires_document_retry(response_text: str) -> bool:
    normalized = (response_text or "").strip().lower()
    if not normalized:
        return True
    return any(pattern in normalized for pattern in DOCUMENT_RETRY_PATTERNS)


def normalize_document_response(response_text: str) -> str:
    normalized = (response_text or "").strip()
    if not normalized:
        return DOCUMENT_NO_INFORMATION_RESPONSE

    lowered = normalized.lower()
    if any(pattern in lowered for pattern in DOCUMENT_NO_INFO_PATTERNS):
        return DOCUMENT_NO_INFORMATION_RESPONSE

    return normalized


async def restore_chat_history(
    conversation_writer: RedisConversationWriteCoordinator,
    username: str,
    thread_id: str,
    history: list[dict[str, Any]],
) -> None:
    await conversation_writer.replace_thread_snapshot(username, thread_id, history)


async def run_document_job(
    *,
    gateway: LLMGateway,
    conversation_writer: RedisConversationWriteCoordinator,
    username: str,
    thread_id: str,
    model_info: Dict[str, str],
    prompt: str,
    history: list[dict[str, Any]],
    history_entry: str,
    file_chat: Optional[dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any]]:
    job_id = await enqueue_document_job(
        gateway=gateway,
        conversation_writer=conversation_writer,
        username=username,
        thread_id=thread_id,
        model_info=model_info,
        prompt=prompt,
        history=history,
        history_entry=history_entry,
        file_chat=file_chat,
    )
    result = await wait_for_terminal_job(gateway, job_id, settings.LLM_JOB_DEADLINE_SECONDS)
    return job_id, result


async def enqueue_document_job(
    *,
    gateway: LLMGateway,
    conversation_writer: RedisConversationWriteCoordinator,
    username: str,
    thread_id: str,
    model_info: Dict[str, str],
    prompt: str,
    history: list[dict[str, Any]],
    history_entry: str,
    file_chat: Optional[dict[str, Any]] = None,
) -> str:
    limited_history = apply_history_budget(history)
    job_id = await gateway.enqueue_job(
        username=username,
        thread_id=thread_id,
        model_key=model_info["key"],
        model_name=model_info["name"],
        prompt=prompt,
        history=limited_history,
        job_kind=JOB_KIND_FILE_CHAT,
        file_chat=file_chat,
    )
    await conversation_writer.append_message(username, "user", history_entry, thread_id=thread_id)
    return job_id


async def stage_uploads_for_parser(
    files: list[UploadFile],
    *,
    username: Optional[str] = None,
) -> dict[str, Any]:
    return await parser_stage.stage_uploads_to_shared_root(
        files,
        staging_root=settings.PARSER_STAGING_ROOT,
        username=username,
    )


def build_parser_job_metadata(
    *,
    staged_files: list[dict[str, Any]],
    requested_model: Optional[str],
) -> dict[str, Any]:
    metadata = {
        "phase": "staged",
        "files": [
            {
                "name": file_info["name"],
                "safe_name": file_info["safe_name"],
                "size": int(file_info["size"]),
                "content_type": file_info["content_type"],
            }
            for file_info in staged_files
        ],
    }
    normalized_requested_model = (requested_model or "").strip()
    if normalized_requested_model:
        metadata["requested_model"] = normalized_requested_model
    return metadata


async def enqueue_parser_job(
    *,
    gateway: LLMGateway,
    username: str,
    thread_id: str,
    model_info: Dict[str, str],
    message: str,
    history: list[dict[str, Any]],
    staging_id: str,
    staged_files: list[dict[str, Any]],
    requested_model: Optional[str] = None,
) -> str:
    if not settings.ENABLE_PARSER_STAGE:
        raise RuntimeError("Parser stage is disabled")

    limited_history = apply_history_budget(history)
    return await gateway.enqueue_job(
        username=username,
        thread_id=thread_id,
        model_key=model_info["key"],
        model_name=model_info["name"],
        prompt=(message or "").strip(),
        history=limited_history,
        job_kind=JOB_KIND_PARSE,
        workload_class=WORKLOAD_PARSE,
        staging_id=staging_id,
        parser_metadata=build_parser_job_metadata(
            staged_files=staged_files,
            requested_model=requested_model,
        ),
    )


def parser_public_json_timeout_seconds() -> int:
    return settings.PARSER_JOB_TIMEOUT_SECONDS + settings.LLM_JOB_DEADLINE_SECONDS


async def run_parser_public_job(
    *,
    gateway: LLMGateway,
    conversation_writer: RedisConversationWriteCoordinator,
    username: str,
    thread_id: str,
    model_info: Dict[str, str],
    message: str,
    history: list[dict[str, Any]],
    history_entry: str,
    staging_id: str,
    staged_files: list[dict[str, Any]],
    requested_model: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    job_id = await enqueue_parser_public_job(
        gateway=gateway,
        conversation_writer=conversation_writer,
        username=username,
        thread_id=thread_id,
        model_info=model_info,
        message=message,
        history=history,
        history_entry=history_entry,
        staging_id=staging_id,
        staged_files=staged_files,
        requested_model=requested_model,
    )
    result = await wait_for_terminal_job(gateway, job_id, parser_public_json_timeout_seconds())
    return job_id, result


async def enqueue_parser_public_job(
    *,
    gateway: LLMGateway,
    conversation_writer: RedisConversationWriteCoordinator,
    username: str,
    thread_id: str,
    model_info: Dict[str, str],
    message: str,
    history: list[dict[str, Any]],
    history_entry: str,
    staging_id: str,
    staged_files: list[dict[str, Any]],
    requested_model: Optional[str] = None,
) -> str:
    job_id = await enqueue_parser_job(
        gateway=gateway,
        username=username,
        thread_id=thread_id,
        model_info=model_info,
        message=message,
        history=history,
        staging_id=staging_id,
        staged_files=staged_files,
        requested_model=requested_model,
    )
    await conversation_writer.append_message(username, "user", history_entry, thread_id=thread_id)
    return job_id


async def stage_uploads(
    files: list[UploadFile],
    *,
    username: Optional[str] = None,
) -> tuple[tempfile.TemporaryDirectory[str], list[dict[str, Any]]]:
    temp_dir = tempfile.TemporaryDirectory(prefix="ai-agent-upload-")
    try:
        staged_files = await parser_stage.stage_uploads_to_directory(
            files,
            target_dir=Path(temp_dir.name),
            username=username,
        )
    except Exception:
        temp_dir.cleanup()
        raise

    return temp_dir, staged_files


def log_file_parse_observability(
    *,
    username: str,
    job_kind: str,
    file_count: int,
    staging_ms: int,
    parse_ms: int,
    original_doc_chars: int,
    trimmed_doc_chars: int,
    terminal_status: str,
    error_type: str,
) -> None:
    parser_stage.log_file_pipeline_observability(
        username=username,
        job_kind=job_kind,
        file_count=file_count,
        receive_ms=staging_ms,
        parse_ms=parse_ms,
        doc_chars=trimmed_doc_chars,
        original_doc_chars=original_doc_chars,
        trimmed_doc_chars=trimmed_doc_chars,
        terminal_status=terminal_status,
        error_type=error_type,
        target_logger=logger,
    )


def build_file_chat_job_metadata(
    *,
    retry_prompt: Optional[str],
    staged_files: list[dict[str, Any]],
    doc_chars: int = 0,
    thread_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "retry_prompt": (retry_prompt or "").strip() or None,
        "suppress_token_stream": True,
        "doc_chars": max(0, int(doc_chars)),
        "thread_id": normalize_chat_thread_id(thread_id),
        "files": [
            {
                "name": file_info["name"],
                "size": int(file_info["size"]),
            }
            for file_info in staged_files
        ],
    }


def wants_event_stream(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept


def build_token_payload(user_info: Dict[str, Any], token_type: str) -> Dict[str, Any]:
    identity = enrich_identity_session_fields(user_info, auth_source=user_info.get("auth_source", AUTH_SOURCE_PASSWORD))
    return {
        "sub": identity["username"],
        "canonical_principal": identity["canonical_principal"],
        "display_name": identity["display_name"],
        "email": identity["email"],
        "groups": identity.get("groups", []),
        "model": identity["model"],
        "model_description": identity["model_description"],
        "model_key": identity["model_key"],
        "auth_source": identity["auth_source"],
        "auth_time": identity["auth_time"],
        "directory_checked_at": identity["directory_checked_at"],
        "identity_version": identity["identity_version"],
        "type": token_type,
    }


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: Optional[str] = None,
    csrf_token: Optional[str] = None,
) -> None:
    base_cookie_params = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
        "path": "/",
    }
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **base_cookie_params,
    )
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=f"Bearer {refresh_token}",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            expires=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            **base_cookie_params,
        )
    if csrf_token:
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            expires=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            httponly=False,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            domain=settings.COOKIE_DOMAIN,
            path="/",
        )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie("refresh_token", path="/", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie("csrf_token", path="/", domain=settings.COOKIE_DOMAIN)


def local_admin_enabled() -> bool:
    return bool(settings.LOCAL_ADMIN_ENABLED)


def local_admin_username() -> str:
    return normalize_username(settings.LOCAL_ADMIN_USERNAME or "admin_ai")


def local_admin_env_state() -> Dict[str, Any]:
    base_env_revision = hashlib.sha256(
        json.dumps(
            {
                "enabled": bool(settings.LOCAL_ADMIN_ENABLED),
                "username": local_admin_username(),
                "password_hash": str(settings.LOCAL_ADMIN_PASSWORD_HASH or ""),
                "force_rotate": bool(settings.LOCAL_ADMIN_FORCE_ROTATE),
                "bootstrap_required": bool(settings.LOCAL_ADMIN_BOOTSTRAP_REQUIRED),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    state = {
        "enabled": bool(settings.LOCAL_ADMIN_ENABLED),
        "username": local_admin_username(),
        "password_hash": str(settings.LOCAL_ADMIN_PASSWORD_HASH or "").strip(),
        "force_rotate": bool(settings.LOCAL_ADMIN_FORCE_ROTATE),
        "bootstrap_required": bool(settings.LOCAL_ADMIN_BOOTSTRAP_REQUIRED),
        "runtime_override": False,
        "base_env_revision": base_env_revision,
    }
    state["state_revision"] = build_local_admin_state_revision(state)
    return state


def local_admin_state_is_configured(state: Dict[str, Any]) -> bool:
    return bool(state.get("enabled")) and bool(state.get("username")) and bool(state.get("password_hash"))


def local_admin_rotation_required(state: Dict[str, Any]) -> bool:
    return bool(state.get("force_rotate")) or bool(state.get("bootstrap_required"))


def build_local_admin_identity(
    state: Dict[str, Any],
    *,
    rotation_required: Optional[bool] = None,
) -> Dict[str, Any]:
    username = str(state.get("username") or local_admin_username() or "admin_ai")
    requires_rotation = local_admin_rotation_required(state) if rotation_required is None else bool(rotation_required)
    return {
        "username": username,
        "display_name": username,
        "email": "break-glass admin",
        "canonical_principal": f"local-admin:{username}",
        "groups": ["local-break-glass-admin"],
        "auth_source": AUTH_SOURCE_LOCAL_ADMIN,
        "local_admin": True,
        "dashboard_only": True,
        "rotation_required": requires_rotation,
        "state_revision": str(state.get("state_revision") or ""),
    }


def build_local_admin_login_rate_subject(request: Request, username: str) -> str:
    return f"local-admin:{build_login_rate_subject(request, username)}"


def set_local_admin_cookies(
    response: Response,
    access_token: str,
    *,
    csrf_token: Optional[str] = None,
) -> None:
    base_cookie_params = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
        "path": "/admin",
    }
    response.set_cookie(
        key=LOCAL_ADMIN_ACCESS_COOKIE_NAME,
        value=f"Bearer {access_token}",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **base_cookie_params,
    )
    if csrf_token:
        response.set_cookie(
            key=LOCAL_ADMIN_CSRF_COOKIE_NAME,
            value=csrf_token,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            httponly=False,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            domain=settings.COOKIE_DOMAIN,
            path="/admin",
        )


def clear_local_admin_cookies(response: Response) -> None:
    response.delete_cookie(LOCAL_ADMIN_ACCESS_COOKIE_NAME, path="/admin", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(LOCAL_ADMIN_CSRF_COOKIE_NAME, path="/admin", domain=settings.COOKIE_DOMAIN)


def get_or_create_local_admin_csrf_token(request: Request) -> str:
    existing = request.cookies.get(LOCAL_ADMIN_CSRF_COOKIE_NAME)
    if existing and len(existing) >= 32:
        return existing
    return generate_csrf_token()


def enforce_local_admin_csrf(request: Request, *, form_token: Optional[str] = None) -> None:
    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    expected_origin = f"{request.url.scheme}://{host}"
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin and origin != expected_origin:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not origin and referer:
        parsed = urlparse(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        if referer_origin != expected_origin:
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    csrf_cookie = request.cookies.get(LOCAL_ADMIN_CSRF_COOKIE_NAME)
    csrf_candidate = form_token or request.headers.get("X-CSRF-Token")
    if not csrf_cookie or not csrf_candidate or not secrets.compare_digest(csrf_cookie, csrf_candidate):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def local_admin_page_context(**extra: Any) -> Dict[str, Any]:
    return {
        "local_admin_enabled": local_admin_enabled(),
        "local_admin_login_path": LOCAL_ADMIN_LOGIN_PATH,
        **extra,
    }


async def get_local_admin_redis_client(request: Request) -> Any:
    gateway = getattr(request.app.state, "llm_gateway", None)
    redis_client = getattr(gateway, "redis", None)
    if redis_client is None:
        raise HTTPException(status_code=503, detail=AUTH_BACKEND_UNAVAILABLE_ERROR)
    return redis_client


async def load_local_admin_state(request: Request) -> Dict[str, Any]:
    env_state = local_admin_env_state()
    if not local_admin_enabled():
        return env_state
    if not local_admin_state_is_configured(env_state):
        return env_state

    redis_client = await get_local_admin_redis_client(request)
    raw_payload = await redis_client.get(LOCAL_ADMIN_STATE_REDIS_KEY)
    if not raw_payload:
        payload = dict(env_state)
        await redis_client.set(LOCAL_ADMIN_STATE_REDIS_KEY, json.dumps(payload, sort_keys=True))
        return payload

    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8", errors="ignore")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        payload = {}

    if not isinstance(payload, dict) or payload.get("base_env_revision") != env_state["base_env_revision"]:
        payload = dict(env_state)
        await redis_client.set(LOCAL_ADMIN_STATE_REDIS_KEY, json.dumps(payload, sort_keys=True))
        return payload

    merged_state = dict(env_state)
    merged_state.update(
        {
            "enabled": bool(payload.get("enabled", env_state["enabled"])),
            "username": normalize_username(str(payload.get("username") or env_state["username"])),
            "password_hash": str(payload.get("password_hash") or env_state["password_hash"]).strip(),
            "force_rotate": bool(payload.get("force_rotate", env_state["force_rotate"])),
            "bootstrap_required": bool(payload.get("bootstrap_required", env_state["bootstrap_required"])),
            "runtime_override": bool(payload.get("runtime_override", False)),
            "base_env_revision": str(payload.get("base_env_revision") or env_state["base_env_revision"]),
            "rotated_at": int(payload.get("rotated_at") or 0),
        }
    )
    merged_state["state_revision"] = build_local_admin_state_revision(merged_state)
    return merged_state


async def persist_local_admin_state(request: Request, state: Dict[str, Any]) -> Dict[str, Any]:
    stored_state = {
        "enabled": bool(state.get("enabled", False)),
        "username": normalize_username(str(state.get("username") or "")),
        "password_hash": str(state.get("password_hash") or "").strip(),
        "force_rotate": bool(state.get("force_rotate", False)),
        "bootstrap_required": bool(state.get("bootstrap_required", False)),
        "runtime_override": bool(state.get("runtime_override", False)),
        "base_env_revision": str(state.get("base_env_revision") or ""),
        "rotated_at": int(state.get("rotated_at") or 0),
    }
    stored_state["state_revision"] = build_local_admin_state_revision(stored_state)
    redis_client = await get_local_admin_redis_client(request)
    await redis_client.set(LOCAL_ADMIN_STATE_REDIS_KEY, json.dumps(stored_state, sort_keys=True))
    return stored_state


def build_local_admin_access_token_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    identity = build_local_admin_identity(state)
    return {
        "sub": identity["username"],
        "canonical_principal": identity["canonical_principal"],
        "display_name": identity["display_name"],
        "email": identity["email"],
        "groups": identity["groups"],
        "auth_source": LOCAL_ADMIN_AUTH_SOURCE,
        "local_admin": True,
        "dashboard_only": True,
        "state_revision": str(state.get("state_revision") or ""),
        "rotation_required": local_admin_rotation_required(state),
        "type": LOCAL_ADMIN_ACCESS_TOKEN_TYPE,
    }


async def issue_local_admin_session_response(
    request: Request,
    *,
    state: Dict[str, Any],
    redirect_url: str,
) -> RedirectResponse:
    access_token = create_access_token(
        build_local_admin_access_token_payload(state),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    response = RedirectResponse(url=redirect_url, status_code=303)
    set_local_admin_cookies(response, access_token, csrf_token=get_or_create_local_admin_csrf_token(request))
    return response


async def revoke_local_admin_session_token(request: Request) -> None:
    redis_client = await get_local_admin_redis_client(request)
    raw_token = request.cookies.get(LOCAL_ADMIN_ACCESS_COOKIE_NAME)
    if raw_token:
        await revoke_token(redis_client, raw_token)


async def get_current_local_admin_session(request: Request) -> Optional[Dict[str, Any]]:
    raw_token = request.cookies.get(LOCAL_ADMIN_ACCESS_COOKIE_NAME)
    token = extract_bearer_token(raw_token)
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        logger.warning("Local admin JWT decode failed: %s", exc)
        return None

    if payload.get("type") != LOCAL_ADMIN_ACCESS_TOKEN_TYPE or not payload.get("local_admin"):
        return None

    try:
        state = await load_local_admin_state(request)
    except HTTPException as exc:
        if exc.status_code == 503:
            logger.error("Local admin auth backend unavailable while resolving dashboard session")
            return None
        raise

    if not local_admin_state_is_configured(state):
        return None

    redis_client = await get_local_admin_redis_client(request)
    if await is_token_revoked(redis_client, payload):
        logger.warning("Rejected revoked local admin JWT for subject %s", payload.get("sub"))
        return None

    if payload.get("sub") != state["username"]:
        return None
    if payload.get("state_revision") != state["state_revision"]:
        return None

    return build_local_admin_identity(state)


async def get_current_local_admin_session_required(
    request: Request,
    current_local_admin: Optional[Dict[str, Any]] = Depends(get_current_local_admin_session),
) -> Dict[str, Any]:
    if not local_admin_enabled():
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)
    state = await load_local_admin_state(request)
    if not local_admin_state_is_configured(state):
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)
    if not current_local_admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return current_local_admin


async def get_local_admin_rotation_session_required(
    request: Request,
    current_local_admin: Dict[str, Any] = Depends(get_current_local_admin_session_required),
) -> Dict[str, Any]:
    if not current_local_admin.get("rotation_required"):
        raise HTTPException(status_code=403, detail="Password rotation is not required")
    return current_local_admin


@lru_cache(maxsize=16)
def parse_trusted_proxy_source_cidrs(raw_value: str) -> tuple[ipaddress._BaseNetwork, ...]:
    cidrs: list[ipaddress._BaseNetwork] = []
    for item in raw_value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        cidrs.append(ipaddress.ip_network(candidate, strict=False))
    return tuple(cidrs)


@lru_cache(maxsize=16)
def parse_admin_dashboard_allowed_users(raw_value: str) -> frozenset[str]:
    allowed_users: set[str] = set()
    for item in raw_value.split(","):
        normalized = normalize_username(item)
        if normalized:
            allowed_users.add(normalized)
    return frozenset(allowed_users)


def get_request_client_host(request: Request) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


def request_comes_from_trusted_proxy_source(request: Request) -> bool:
    client_host = get_request_client_host(request)
    if not client_host:
        return False
    trusted_cidrs = (settings.TRUSTED_PROXY_SOURCE_CIDRS or "").strip()
    if not trusted_cidrs:
        return False
    try:
        client_ip = ipaddress.ip_address(client_host)
    except ValueError:
        logger.warning("Rejected trusted proxy check for non-IP client host: %s", client_host)
        return False
    try:
        return any(client_ip in network for network in parse_trusted_proxy_source_cidrs(trusted_cidrs))
    except ValueError:
        logger.warning("Invalid TRUSTED_PROXY_SOURCE_CIDRS value configured; trusted proxy checks are disabled")
        return False


def build_login_rate_subject(request: Request, username: str) -> str:
    client_host = ""
    if request_comes_from_trusted_proxy_source(request):
        forwarded_for = request.headers.get("x-forwarded-for", "")
        real_ip = request.headers.get("x-real-ip", "")
        client_host = real_ip or (forwarded_for.split(",", 1)[0].strip() if forwarded_for else "")
    if not client_host:
        client_host = get_request_client_host(request) or "unknown"
    normalized = normalize_username(username) or username.strip().lower() or "anonymous"
    return f"{client_host}:{normalized[:128]}"


def user_is_admin(user_info: Dict[str, Any]) -> bool:
    groups = [group.lower() for group in user_info.get("groups", [])]
    return any(
        group in {"domain admins", "admins", "administrators", "ai-admins", "ai-admin"}
        or group.endswith("-admins")
        or group.endswith("_admins")
        for group in groups
    )


def user_can_access_admin_dashboard(user_info: Dict[str, Any]) -> bool:
    username = normalize_username(user_info.get("username") or "")
    allowed_users = parse_admin_dashboard_allowed_users(settings.ADMIN_DASHBOARD_USERS or "")
    return bool(username) and username in allowed_users


async def get_admin_dashboard_user_required(
    current_user: Dict[str, Any] = Depends(get_current_user_required),
) -> Dict[str, Any]:
    if not user_can_access_admin_dashboard(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return current_user


async def get_admin_dashboard_identity_required(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
    current_local_admin: Optional[Dict[str, Any]] = Depends(get_current_local_admin_session),
) -> Dict[str, Any]:
    if current_user and user_can_access_admin_dashboard(current_user):
        identity = dict(current_user)
        identity["dashboard_auth_mode"] = "ad"
        identity["home_href"] = "/chat"
        identity["logout_path"] = "/logout"
        identity["csrf_cookie_name"] = "csrf_token"
        identity["logout_redirect"] = "/login"
        identity["session_status_label"] = "Активен • Корпоративный доступ"
        return identity

    if current_local_admin:
        if current_local_admin.get("rotation_required"):
            raise HTTPException(status_code=403, detail=LOCAL_ADMIN_ROTATION_REQUIRED_ERROR)
        identity = dict(current_local_admin)
        identity["dashboard_auth_mode"] = "local_admin"
        identity["home_href"] = "/admin/dashboard"
        identity["logout_path"] = LOCAL_ADMIN_LOGOUT_PATH
        identity["csrf_cookie_name"] = LOCAL_ADMIN_CSRF_COOKIE_NAME
        identity["logout_redirect"] = LOCAL_ADMIN_LOGIN_PATH
        identity["session_status_label"] = "Активен • Break-glass admin"
        return identity

    raise HTTPException(status_code=403, detail="Forbidden")


def get_or_create_csrf_token(request: Request) -> str:
    existing = request.cookies.get("csrf_token")
    if existing and len(existing) >= 32:
        return existing
    return generate_csrf_token()


def request_uses_bearer_auth_without_session(request: Request) -> bool:
    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        return False
    scheme, _, _ = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return not bool(request.cookies.get("access_token"))


def get_request_path(request: Request) -> str:
    request_url = getattr(request, "url", None)
    if request_url is not None:
        path = getattr(request_url, "path", None)
        if path:
            return str(path)
    request_scope = getattr(request, "scope", None)
    if isinstance(request_scope, dict):
        return str(request_scope.get("path") or "")
    return ""


def get_request_method(request: Request) -> str:
    return str(getattr(request, "method", "GET") or "GET").upper()


def get_reserved_auth_proxy_headers(request: Request) -> list[str]:
    return sorted(header for header in RESERVED_AUTH_PROXY_HEADERS if request.headers.get(header))


def trusted_proxy_sso_enabled() -> bool:
    return settings.SSO_ENABLED and settings.TRUSTED_AUTH_PROXY_ENABLED


def request_allows_trusted_proxy_headers(request: Request) -> bool:
    return (
        trusted_proxy_sso_enabled()
        and get_request_method(request) == "GET"
        and get_request_path(request) == settings.SSO_LOGIN_PATH
        and request_comes_from_trusted_proxy_source(request)
    )


def reject_untrusted_auth_proxy_headers(request: Request) -> None:
    present_headers = get_reserved_auth_proxy_headers(request)
    if not present_headers:
        return
    if request_allows_trusted_proxy_headers(request):
        return
    logger.warning(
        "Rejected request with reserved auth proxy headers outside the trusted SSO entry path: %s",
        present_headers,
    )
    raise HTTPException(status_code=400, detail="Unsupported authentication headers")


def build_http_exception_response(exc: HTTPException) -> JSONResponse:
    payload = {"detail": exc.detail}
    response = JSONResponse(payload, status_code=exc.status_code)
    if exc.headers:
        for header, value in exc.headers.items():
            response.headers[header] = value
    return response


def parse_trusted_proxy_groups_header(raw_value: Optional[str]) -> list[str]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid trusted proxy authentication headers") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Invalid trusted proxy authentication headers")
    groups: list[str] = []
    for item in payload:
        candidate = str(item).strip()
        if candidate:
            groups.append(candidate)
    return groups


def build_trusted_proxy_sso_identity(request: Request) -> Dict[str, Any]:
    if not trusted_proxy_sso_enabled():
        raise HTTPException(status_code=404, detail="SSO login is disabled")
    if not request_allows_trusted_proxy_headers(request):
        raise HTTPException(status_code=400, detail="Unsupported authentication headers")

    username = normalize_username(request.headers.get("x-authenticated-user") or "")
    canonical_principal = (request.headers.get("x-authenticated-principal") or "").strip()
    if not username or not canonical_principal:
        raise HTTPException(status_code=401, detail="SSO identity is unavailable")
    if normalize_username(canonical_principal) != username:
        raise HTTPException(status_code=401, detail="SSO identity is inconsistent")

    return enrich_identity_session_fields(
        {
            "username": username,
            "canonical_principal": canonical_principal,
            "display_name": (request.headers.get("x-authenticated-name") or username).strip(),
            "email": (request.headers.get("x-authenticated-email") or f"{username}@{settings.LDAP_DOMAIN}").strip(),
            "groups": parse_trusted_proxy_groups_header(request.headers.get("x-authenticated-groups")),
            "auth_source": AUTH_SOURCE_SSO,
        },
        auth_source=AUTH_SOURCE_SSO,
    )


async def revoke_request_session_tokens(request: Request) -> None:
    redis_client = getattr(request.app.state.llm_gateway, "redis", None)
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    if (access_token or refresh_token) and redis_client is None:
        raise HTTPException(status_code=503, detail=AUTH_BACKEND_UNAVAILABLE_ERROR)
    if access_token:
        await revoke_token(redis_client, access_token)
    if refresh_token:
        await revoke_token(redis_client, refresh_token)


def enforce_csrf(request: Request) -> None:
    if request_uses_bearer_auth_without_session(request):
        return

    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    expected_origin = f"{request.url.scheme}://{host}"
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if origin and origin != expected_origin:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not origin and referer:
        parsed = urlparse(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        if referer_origin != expected_origin:
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    csrf_cookie = request.cookies.get("csrf_token")
    csrf_header = request.headers.get("X-CSRF-Token")
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def prepare_messages(messages: list[dict]) -> list[dict]:
    prepared = []
    for index, message in enumerate(messages):
        role = message.get("role", "assistant")
        content = message.get("content", "")
        prepared.append(
            {
                "id": index,
                "role": role,
                "content": content,
                "html": render_markdown(content) if role == "assistant" else None,
            }
        )
    return prepared


def prepare_db_store_messages(messages: list[Any]) -> list[dict[str, str]]:
    return [
        {
            "role": str(getattr(message, "role", "assistant")),
            "content": str(getattr(message, "content", "")),
        }
        for message in messages
    ]


def build_db_thread_summaries_from_store(
    chat_store: AsyncChatStore,
    db_store: Any,
    username: str,
) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    for thread in db_store.list_threads(username):
        history = prepare_db_store_messages(db_store.get_messages(username, thread.thread_id))
        threads.append(
            {
                "id": normalize_chat_thread_id(thread.thread_id),
                "title": chat_store.build_thread_title(history),
                "updatedAt": max(0, int(thread.updated_at.timestamp() * 1000)),
                "messageCount": len(history),
            }
        )
    return threads


def summarize_thread_list_for_cutover_compare(threads: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    return [
        (
            normalize_chat_thread_id(thread.get("id")),
            str(thread.get("title") or "Новый чат").strip() or "Новый чат",
            max(0, int(thread.get("messageCount") or 0)),
        )
        for thread in threads
    ]


async def resolve_thread_summaries_for_read_response(
    request: Request,
    *,
    username: str,
    redis_threads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not settings.PERSISTENT_DB_READ_THREADS:
        return redis_threads

    db_store = getattr(request.app.state, "conversation_db_store", None)
    if db_store is None:
        logger.warning(
            "Conversation DB thread-list cutover enabled but DB store unavailable for user %s; falling back to Redis",
            username,
        )
        return redis_threads

    chat_store = request.app.state.chat_store
    try:
        db_threads = await asyncio.to_thread(
            build_db_thread_summaries_from_store,
            chat_store,
            db_store,
            username,
        )
    except Exception:
        logger.exception(
            "Conversation DB thread-list cutover failed for user %s; falling back to Redis",
            username,
        )
        return redis_threads

    if summarize_thread_list_for_cutover_compare(redis_threads) == summarize_thread_list_for_cutover_compare(db_threads):
        logger.info(
            "Conversation DB thread-list cutover serving DB-backed summaries for user %s (threads=%s)",
            username,
            len(db_threads),
        )
        return db_threads

    logger.warning(
        "Conversation DB thread-list cutover fallback to Redis for user %s (redis_threads=%s db_threads=%s)",
        username,
        len(redis_threads),
        len(db_threads),
    )
    return redis_threads


async def maybe_run_shadow_compare_for_conversation_read(
    request: Request,
    *,
    username: str,
    thread_id: str,
    history: list[dict[str, Any]],
) -> None:
    if not settings.PERSISTENT_DB_SHADOW_COMPARE:
        return

    db_store = getattr(request.app.state, "conversation_db_store", None)
    if db_store is None:
        logger.warning(
            "Conversation shadow compare enabled but DB store unavailable for user %s thread %s",
            username,
            thread_id,
        )
        return

    try:
        result = await asyncio.to_thread(
            compare_history_snapshot_to_store,
            history,
            db_store,
            username,
            thread_id,
        )
    except Exception:
        logger.exception(
            "Conversation shadow compare failed for user %s thread %s",
            username,
            thread_id,
        )
        return

    if result.status == PARITY_MATCHED:
        logger.info(
            "Conversation shadow compare matched for user %s thread %s (source=%s db=%s)",
            username,
            thread_id,
            result.source_message_count,
            result.db_message_count,
        )
        return

    logger.warning(
        "Conversation shadow compare %s for user %s thread %s (source=%s db=%s)",
        result.status,
        username,
        thread_id,
        result.source_message_count,
        result.db_message_count,
    )


async def resolve_thread_messages_for_read_response(
    request: Request,
    *,
    username: str,
    thread_id: str,
    redis_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not settings.PERSISTENT_DB_READ_MESSAGES:
        await maybe_run_shadow_compare_for_conversation_read(
            request,
            username=username,
            thread_id=thread_id,
            history=redis_history,
        )
        return redis_history

    db_store = getattr(request.app.state, "conversation_db_store", None)
    if db_store is None:
        logger.warning(
            "Conversation DB read cutover enabled but DB store unavailable for user %s thread %s; falling back to Redis",
            username,
            thread_id,
        )
        return redis_history

    try:
        db_messages = await asyncio.to_thread(db_store.get_messages, username, thread_id)
        result = compare_history_snapshot_to_messages(
            redis_history,
            db_messages,
            thread_id,
        )
    except Exception:
        logger.exception(
            "Conversation DB read cutover failed for user %s thread %s; falling back to Redis",
            username,
            thread_id,
        )
        return redis_history

    if result.status in {PARITY_MATCHED, PARITY_EMPTY_THREAD}:
        logger.info(
            "Conversation DB read cutover serving DB-backed messages for user %s thread %s (source=%s db=%s)",
            username,
            thread_id,
            result.source_message_count,
            result.db_message_count,
        )
        return prepare_db_store_messages(db_messages)

    logger.warning(
        "Conversation DB read cutover fallback to Redis due to %s for user %s thread %s (source=%s db=%s)",
        result.status,
        username,
        thread_id,
        result.source_message_count,
        result.db_message_count,
    )
    return redis_history


def resolve_model_identifier(
    model_identifier: Optional[str],
    allowed_models: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, str]]:
    candidate = (model_identifier or "").strip()
    if not candidate:
        return None

    if candidate in allowed_models:
        model_info = allowed_models[candidate]
        return {"key": candidate, "name": model_info["name"], "description": model_info["description"]}

    for key, model_info in allowed_models.items():
        if model_info["name"] == candidate:
            return {"key": key, "name": model_info["name"], "description": model_info["description"]}

    return None


def resolve_model(
    current_user: Dict[str, Any],
    available_models: Dict[str, Dict[str, str]],
    *,
    allow_fallback: bool = False,
) -> Dict[str, str]:
    allowed_models = get_allowed_models_for_user(current_user, available_models)
    if not allowed_models:
        raise LookupError(NO_LLM_MODELS_AVAILABLE_ERROR)

    resolved = resolve_model_identifier(current_user.get("model_key"), allowed_models)
    if resolved is not None:
        return resolved

    resolved = resolve_model_identifier(current_user.get("model"), allowed_models)
    if resolved is not None:
        return resolved

    if allow_fallback:
        fallback_key = settings.pick_available_model(allowed_models) or next(iter(allowed_models.keys()))
        fallback = allowed_models[fallback_key]
        return {"key": fallback_key, "name": fallback["name"], "description": fallback["description"]}

    requested = (current_user.get("model_key") or current_user.get("model") or "").strip() or "unknown"
    raise LookupError(f"LLM model not found: {requested}")


def resolve_requested_model(
    current_user: Dict[str, Any],
    available_models: Dict[str, Dict[str, str]],
    requested_model: Optional[str],
    *,
    allow_user_fallback: bool = False,
) -> Dict[str, str]:
    allowed_models = get_allowed_models_for_user(current_user, available_models)
    if not allowed_models:
        raise LookupError(NO_LLM_MODELS_AVAILABLE_ERROR)

    resolved = resolve_model_identifier(requested_model, allowed_models)
    if resolved is not None:
        return resolved

    if (requested_model or "").strip():
        raise LookupError(f"LLM model not found: {requested_model.strip()}")

    return resolve_model(current_user, available_models, allow_fallback=allow_user_fallback)


def get_placeholder_model_info() -> Dict[str, str]:
    placeholder_key = settings.DEFAULT_MODEL or "llm-unavailable"
    return {
        "key": placeholder_key,
        "name": placeholder_key,
        "description": LLM_MODELS_UNAVAILABLE_DESCRIPTION,
    }


def _select_cpu_lightweight_model(allowed_models: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
    for key, model_info in allowed_models.items():
        if key == "phi3:mini" or model_info.get("name") == "phi3:mini":
            return {"key": key, "name": model_info["name"], "description": model_info["description"]}

    lightweight_models = []
    for key, model_info in allowed_models.items():
        size_bytes = int(model_info.get("size") or 0)
        if 0 < size_bytes <= CPU_LIGHTWEIGHT_MODEL_MAX_SIZE_BYTES:
            lightweight_models.append((size_bytes, key, model_info))

    if not lightweight_models:
        return None

    _, key, model_info = min(lightweight_models, key=lambda item: (item[0], item[1]))
    return {"key": key, "name": model_info["name"], "description": model_info["description"]}


async def resolve_runtime_model(
    current_user: Dict[str, Any],
    available_models: Dict[str, Dict[str, str]],
    gateway: LLMGateway,
    requested_model: Optional[str] = None,
    *,
    allow_user_fallback: bool = False,
) -> Dict[str, str]:
    if not available_models:
        raise LookupError(NO_LLM_MODELS_AVAILABLE_ERROR)
    resolved = resolve_requested_model(
        current_user,
        available_models,
        requested_model,
        allow_user_fallback=allow_user_fallback,
    )
    logger.info(
        "Selected runtime model %s for user %s (requested=%s)",
        resolved["key"],
        current_user.get("username", "unknown"),
        (requested_model or current_user.get("model_key") or current_user.get("model") or "").strip() or "auto",
    )
    return resolved


async def build_ready_payload(gateway: LLMGateway) -> Dict[str, Any]:
    redis_ok = False
    if gateway.redis is not None:
        try:
            redis_ok = bool(await gateway.redis.ping())
        except Exception:
            redis_ok = False

    scheduler_status = await gateway.get_scheduler_status()
    scheduler_fresh = False
    scheduler_age_seconds: Optional[int] = None
    if scheduler_status is not None:
        scheduler_age_seconds = max(0, int(time.time()) - int(scheduler_status.get("last_seen") or 0))
        scheduler_fresh = scheduler_age_seconds <= settings.SCHEDULER_HEARTBEAT_TTL_SECONDS

    workers_total = await gateway.list_active_workers()
    working_workers = await gateway.list_working_workers(WORKLOAD_CHAT)
    capacity_ok = await gateway.can_accept_workload(WORKLOAD_CHAT)
    runtime_state = await gateway.get_runtime_state()
    metrics = await gateway.get_basic_metrics()
    return {
        "redis": redis_ok,
        "scheduler": scheduler_fresh,
        "scheduler_age_seconds": scheduler_age_seconds,
        **runtime_state,
        "workers_total": len(workers_total),
        "workers_working": len(working_workers),
        "workers": len(working_workers),
        "capacity": capacity_ok,
        "metrics": metrics,
    }


def build_pending_by_workload(pending: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    by_workload: Dict[str, Dict[str, Any]] = {}
    for queue_key, raw_value in pending.items():
        workload, _, priority = str(queue_key).partition(":")
        count = max(0, int(raw_value or 0))
        bucket = by_workload.setdefault(workload or "unknown", {"total": 0, "by_priority": {}})
        bucket["total"] += count
        if priority:
            bucket["by_priority"][priority] = count
    return by_workload


def compute_average_latency_ms(metrics: Dict[str, Any]) -> Optional[float]:
    total_ms = int(metrics.get("job_latency_total_ms") or 0)
    count = int(metrics.get("job_latency_count") or 0)
    if count <= 0:
        return None
    return round(total_ms / count, 1)


def compute_worker_runtime_status(worker: Dict[str, Any], *, now_ts: int) -> Dict[str, Any]:
    active_jobs = max(0, int(worker.get("active_jobs") or 0))
    age_seconds = max(0, now_ts - int(worker.get("last_seen") or 0))
    if age_seconds > settings.WORKER_HEARTBEAT_TTL_SECONDS:
        status = "stale"
    elif active_jobs > 0:
        status = "working"
    else:
        status = "idle"
    return {
        "worker_id": str(worker.get("worker_id") or ""),
        "pool": str(worker.get("worker_pool") or ""),
        "target_id": str(worker.get("target_id") or ""),
        "target_kind": str(worker.get("target_kind") or ""),
        "active_jobs": active_jobs,
        "last_seen_age_seconds": age_seconds,
        "status": status,
    }


def compute_target_runtime_status(target: Dict[str, Any], *, now_ts: int) -> Dict[str, Any]:
    age_seconds = max(0, now_ts - int(target.get("last_seen") or 0))
    status = "stale" if age_seconds > settings.TARGET_HEARTBEAT_TTL_SECONDS else "online"
    return {
        "target_id": str(target.get("target_id") or ""),
        "target_kind": str(target.get("target_kind") or ""),
        "supports_workloads": list(target.get("supports_workloads") or []),
        "base_capacity_tokens": max(0, int(target.get("base_capacity_tokens") or 0)),
        "cpu_percent": float(target.get("cpu_percent") or 0.0),
        "ram_total_mb": max(0, int(target.get("ram_total_mb") or 0)),
        "ram_free_mb": max(0, int(target.get("ram_free_mb") or 0)),
        "gpu_utilization": float(target.get("gpu_utilization")) if target.get("gpu_utilization") is not None else None,
        "gpu_temperature_c": (
            float(target.get("gpu_temperature_c")) if target.get("gpu_temperature_c") is not None else None
        ),
        "network_rx_bytes": max(0, int(target.get("network_rx_bytes") or 0)) if target.get("network_rx_bytes") is not None else None,
        "network_tx_bytes": max(0, int(target.get("network_tx_bytes") or 0)) if target.get("network_tx_bytes") is not None else None,
        "network_scope": str(target.get("network_scope") or ""),
        "vram_free_mb": max(0, int(target.get("vram_free_mb") or 0)),
        "vram_total_mb": max(0, int(target.get("vram_total_mb") or 0)),
        "loaded_models": list(target.get("loaded_models") or []),
        "last_seen_age_seconds": age_seconds,
        "status": status,
    }


def build_dashboard_warnings(*, ready_payload: Dict[str, Any], pending: Dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not ready_payload.get("redis"):
        warnings.append("Redis недоступен")
    if not ready_payload.get("scheduler"):
        warnings.append("Scheduler heartbeat устарел")
    if not ready_payload.get("capacity"):
        warnings.append("Свободная chat capacity недоступна")
    if int(ready_payload.get("workers_working") or 0) <= 0:
        warnings.append("Нет активных chat workers")
    chat_backlog = sum(count for key, count in pending.items() if str(key).startswith("chat:"))
    if chat_backlog > 0:
        warnings.append(f"В очереди chat ожидают {chat_backlog} задач")
    return warnings


async def build_admin_dashboard_summary(gateway: LLMGateway) -> Dict[str, Any]:
    ready_payload = await build_ready_payload(gateway)
    pending = dict(ready_payload.get("pending") or {})
    metrics = dict(ready_payload.get("metrics") or {})
    active_workers = await gateway.list_active_workers()
    active_targets = await gateway.list_active_targets()
    now_ts = int(time.time())
    ready = (
        bool(ready_payload.get("redis"))
        and bool(ready_payload.get("scheduler"))
        and int(ready_payload.get("workers_working") or 0) > 0
        and bool(ready_payload.get("capacity"))
    )
    worker_rows = [compute_worker_runtime_status(worker, now_ts=now_ts) for worker in active_workers]
    target_rows = [compute_target_runtime_status(target, now_ts=now_ts) for target in active_targets]
    active_models = sorted(
        {
            model_name
            for target in target_rows
            for model_name in target.get("loaded_models", [])
            if str(model_name).strip()
        }
    )
    return {
        "overall_status": "ready" if ready else "degraded",
        "readiness_status": "ready" if ready else "not_ready",
        "health_status": "ok" if ready_payload.get("redis") and ready_payload.get("scheduler") else "degraded",
        "redis": bool(ready_payload.get("redis")),
        "scheduler": bool(ready_payload.get("scheduler")),
        "scheduler_status": "healthy" if ready_payload.get("scheduler") else "stale",
        "scheduler_age_seconds": ready_payload.get("scheduler_age_seconds"),
        "queue_depth": max(0, int(metrics.get("queue_depth") or 0)),
        "active_jobs": max(0, int(ready_payload.get("active_jobs") or 0)),
        "workers_total": max(0, int(ready_payload.get("workers_total") or 0)),
        "workers_working": max(0, int(ready_payload.get("workers_working") or 0)),
        "targets": max(0, int(ready_payload.get("targets") or 0)),
        "capacity": bool(ready_payload.get("capacity")),
        "capacity_scope": WORKLOAD_CHAT,
        "failures": max(0, int(metrics.get("failed_jobs") or 0)),
        "rejected": max(0, int(metrics.get("rejected_jobs") or 0)),
        "avg_latency_ms": compute_average_latency_ms(metrics),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
        "pending": pending,
        "by_workload": build_pending_by_workload(pending),
        "chat_backlog": sum(count for key, count in pending.items() if str(key).startswith("chat:")),
        "parser_backlog": sum(count for key, count in pending.items() if str(key).startswith("parse:")),
        "worker_rows": worker_rows,
        "target_rows": target_rows,
        "active_models": active_models,
        "warnings": build_dashboard_warnings(ready_payload=ready_payload, pending=pending),
    }


async def run_dashboard_telemetry_sampler(gateway: LLMGateway, stop_event: asyncio.Event) -> None:
    previous_sample: Optional[Dict[str, Any]] = None
    last_error_signature: Optional[str] = None
    interval_seconds = max(2, int(settings.ADMIN_DASHBOARD_TELEMETRY_INTERVAL_SECONDS))
    while not stop_event.is_set():
        try:
            summary = await build_admin_dashboard_summary(gateway)
            sample = build_dashboard_live_sample(summary, previous_sample=previous_sample)
            public_sample = sanitize_dashboard_live_sample(sample)
            if public_sample is not None:
                await gateway.store_dashboard_live_sample(public_sample)
                await gateway.append_dashboard_history_sample(public_sample)
                for event in build_dashboard_events(previous_sample, public_sample):
                    await gateway.append_dashboard_event(event)
                previous_sample = sample
            if last_error_signature is not None:
                await gateway.append_dashboard_event(
                    build_dashboard_event(
                        severity="info",
                        source="telemetry_sampler",
                        message="Telemetry sampler recovered",
                    )
                )
                last_error_signature = None
        except Exception as exc:
            logger.exception("Dashboard telemetry sampler failed")
            signature = f"{type(exc).__name__}:{exc}"
            if signature != last_error_signature:
                await gateway.append_dashboard_event(
                    build_dashboard_event(
                        severity="error",
                        source="telemetry_sampler",
                        message="Telemetry sampler error",
                        context={"error": str(exc)},
                    )
                )
                last_error_signature = signature
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue


async def wait_for_terminal_job(gateway: LLMGateway, job_id: str, timeout_seconds: int) -> Dict[str, Any]:
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        job = await gateway.get_job(job_id)
        if not job:
            return {"status": "missing"}
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        await asyncio.sleep(0.25)
    return {"status": "timeout"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.conversation_persistence = None
    app.state.conversation_db_store = None
    app.state.chat_store = AsyncChatStore(settings.REDIS_URL, max_history=100)
    app.state.rate_limiter = AsyncRateLimiter(
        settings.REDIS_URL,
        max_requests=settings.RATE_LIMIT_REQUESTS,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    app.state.login_rate_limiter = AsyncRateLimiter(
        settings.REDIS_URL,
        max_requests=settings.LOGIN_RATE_LIMIT_REQUESTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        namespace="ratelimit:login",
    )
    app.state.llm_gateway = LLMGateway(settings.REDIS_URL)
    app.state.dashboard_telemetry_stop = asyncio.Event()
    app.state.dashboard_telemetry_task = None

    await app.state.chat_store.connect()
    await app.state.rate_limiter.connect()
    await app.state.login_rate_limiter.connect()
    await app.state.llm_gateway.connect()
    startup_models = await asyncio.to_thread(settings.get_available_models)
    if startup_models:
        logger.info("Startup Ollama model catalog: %s", list(startup_models.keys()))
        await app.state.llm_gateway.set_model_catalog(startup_models)
    else:
        logger.error("No LLM models available during application startup")
    app.state.conversation_persistence = await asyncio.to_thread(
        open_conversation_persistence_runtime,
        settings,
    )
    if app.state.conversation_persistence is not None:
        app.state.conversation_db_store = app.state.conversation_persistence.store
    app.state.dashboard_telemetry_task = asyncio.create_task(
        run_dashboard_telemetry_sampler(app.state.llm_gateway, app.state.dashboard_telemetry_stop)
    )
    try:
        yield
    finally:
        app.state.dashboard_telemetry_stop.set()
        dashboard_task = app.state.dashboard_telemetry_task
        if dashboard_task is not None:
            dashboard_task.cancel()
            with suppress(asyncio.CancelledError):
                await dashboard_task
        await asyncio.to_thread(
            close_conversation_persistence_runtime,
            app.state.conversation_persistence,
        )
        await app.state.llm_gateway.close()
        await app.state.login_rate_limiter.close()
        await app.state.rate_limiter.close()
        await app.state.chat_store.close()


app = FastAPI(
    title="Corporate AI Assistant",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
REQUEST_COUNT = Counter("app_requests_total", "Total HTTP requests", ["method", "endpoint"])


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    try:
        reject_untrusted_auth_proxy_headers(request)
    except HTTPException as exc:
        return build_http_exception_response(exc)
    response = await call_next(request)
    REQUEST_COUNT.labels(request.method, request.url.path).inc()
    return response


@app.get("/health/live")
async def health_live() -> Response:
    return JSONResponse({"status": "ok"}, status_code=200)


@app.get("/health/ready")
async def health_ready(request: Request) -> Response:
    gateway: LLMGateway = request.app.state.llm_gateway
    payload = await build_ready_payload(gateway)
    ready = payload["redis"] and payload["scheduler"] and payload["workers_working"] > 0 and payload["capacity"]
    payload["status"] = "ready" if ready else "not_ready"
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.get("/health")
async def health(request: Request) -> Response:
    gateway: LLMGateway = request.app.state.llm_gateway
    payload = await build_ready_payload(gateway)
    payload["status"] = "ok" if payload["redis"] and payload["scheduler"] else "degraded"
    return JSONResponse(payload, status_code=200 if payload["status"] == "ok" else 503)


@app.get("/", response_class=HTMLResponse)
async def index(current_user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    return RedirectResponse(url="/chat" if current_user else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if current_user:
        return RedirectResponse(url="/chat", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "sso_login_enabled": trusted_proxy_sso_enabled(),
            "sso_login_path": settings.SSO_LOGIN_PATH,
            "local_admin_enabled": local_admin_enabled(),
            "local_admin_login_path": LOCAL_ADMIN_LOGIN_PATH,
        },
    )


async def sso_login_entry(request: Request, current_user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if not trusted_proxy_sso_enabled():
        raise HTTPException(status_code=404, detail="SSO login is disabled")

    user_info = build_trusted_proxy_sso_identity(request)
    if current_user and current_user.get("canonical_principal") != user_info["canonical_principal"]:
        logger.info(
            "Replacing existing session for %s with trusted proxy SSO identity %s",
            current_user.get("username", "unknown"),
            user_info["username"],
        )

    available_models = await request.app.state.llm_gateway.get_model_catalog()
    try:
        model_info = await resolve_runtime_model(
            user_info,
            available_models,
            request.app.state.llm_gateway,
            allow_user_fallback=True,
        )
    except LookupError:
        logger.error("No LLM models available during trusted proxy SSO login for user %s", user_info["username"])
        model_info = get_placeholder_model_info()

    session_user = {
        **user_info,
        "model": model_info["name"],
        "model_description": model_info["description"],
        "model_key": model_info["key"],
    }
    access_token = create_access_token(
        build_token_payload(session_user, "access"),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_access_token(
        build_token_payload(session_user, "refresh"),
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    await revoke_request_session_tokens(request)
    response = RedirectResponse(url="/chat", status_code=303)
    set_auth_cookies(response, access_token, refresh_token, csrf_token=generate_csrf_token())
    return response


app.add_api_route(settings.SSO_LOGIN_PATH, sso_login_entry, methods=["GET"])


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        await request.app.state.login_rate_limiter.check(build_login_rate_subject(request, username))
        user_info = await asyncio.to_thread(kerberos_auth.authenticate, username, password)
        if not user_info:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "request": request,
                    "error": "Неверное имя пользователя или пароль",
                    "sso_login_enabled": trusted_proxy_sso_enabled(),
                    "sso_login_path": settings.SSO_LOGIN_PATH,
                    "local_admin_enabled": local_admin_enabled(),
                    "local_admin_login_path": LOCAL_ADMIN_LOGIN_PATH,
                },
                status_code=401,
            )

        user_info = enrich_identity_session_fields(user_info, auth_source=AUTH_SOURCE_PASSWORD)
        available_models = await request.app.state.llm_gateway.get_model_catalog()
        try:
            model_info = await resolve_runtime_model(
                user_info,
                available_models,
                request.app.state.llm_gateway,
                allow_user_fallback=True,
            )
        except LookupError:
            logger.error("No LLM models available during login for user %s", user_info["username"])
            model_info = get_placeholder_model_info()
        user_info["model"] = model_info["name"]
        user_info["model_description"] = model_info["description"]
        user_info["model_key"] = model_info["key"]

        access_token = create_access_token(
            build_token_payload(user_info, "access"),
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        refresh_token = create_access_token(
            build_token_payload(user_info, "refresh"),
            expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

        response = RedirectResponse(url="/chat", status_code=303)
        set_auth_cookies(response, access_token, refresh_token, csrf_token=generate_csrf_token())
        return response
    except HTTPException as exc:
        if exc.status_code == 429:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "request": request,
                    "error": LOGIN_RATE_LIMIT_ERROR,
                    "sso_login_enabled": trusted_proxy_sso_enabled(),
                    "sso_login_path": settings.SSO_LOGIN_PATH,
                    "local_admin_enabled": local_admin_enabled(),
                    "local_admin_login_path": LOCAL_ADMIN_LOGIN_PATH,
                },
                status_code=429,
            )
        raise
    except Exception:
        logger.exception("Login error")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "error": GENERIC_AUTH_ERROR,
                "sso_login_enabled": trusted_proxy_sso_enabled(),
                "sso_login_path": settings.SSO_LOGIN_PATH,
                "local_admin_enabled": local_admin_enabled(),
                "local_admin_login_path": LOCAL_ADMIN_LOGIN_PATH,
            },
            status_code=500,
        )


@app.post("/logout")
async def logout(request: Request, current_user: Optional[Dict[str, Any]] = Depends(get_current_user)):
    if current_user:
        enforce_csrf(request)
    redis_client = getattr(request.app.state.llm_gateway, "redis", None)
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    if (access_token or refresh_token) and redis_client is None:
        return JSONResponse({"error": AUTH_BACKEND_UNAVAILABLE_ERROR}, status_code=503)
    if access_token:
        await revoke_token(redis_client, access_token)
    if refresh_token:
        await revoke_token(redis_client, refresh_token)
    response = JSONResponse({"ok": True, "redirect": "/login"})
    clear_auth_cookies(response)
    return response


@app.get(LOCAL_ADMIN_LOGIN_PATH, response_class=HTMLResponse)
async def local_admin_login_page(
    request: Request,
    current_local_admin: Optional[Dict[str, Any]] = Depends(get_current_local_admin_session),
):
    if not local_admin_enabled():
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)
    state = await load_local_admin_state(request)
    if not local_admin_state_is_configured(state):
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)
    if current_local_admin:
        if current_local_admin.get("rotation_required"):
            return RedirectResponse(url=LOCAL_ADMIN_ROTATE_PATH, status_code=303)
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "local_admin_login.html",
        local_admin_page_context(
            request=request,
            local_admin_username=state["username"],
        ),
    )


@app.post(LOCAL_ADMIN_LOGIN_PATH)
async def local_admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not local_admin_enabled():
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)

    state = await load_local_admin_state(request)
    if not local_admin_state_is_configured(state):
        raise HTTPException(status_code=404, detail=LOCAL_ADMIN_NOT_CONFIGURED_ERROR)

    normalized_username = normalize_username(username)
    try:
        await request.app.state.login_rate_limiter.check(build_local_admin_login_rate_subject(request, normalized_username or username))
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        return templates.TemplateResponse(
            request,
            "local_admin_login.html",
            local_admin_page_context(
                request=request,
                local_admin_username=state["username"],
                error=LOGIN_RATE_LIMIT_ERROR,
            ),
            status_code=429,
        )

    if normalized_username != state["username"] or not verify_local_admin_password(password, state["password_hash"]):
        logger.warning(
            "Rejected local break-glass admin login for username=%s from client=%s",
            normalized_username or "<invalid>",
            get_request_client_host(request) or "unknown",
        )
        return templates.TemplateResponse(
            request,
            "local_admin_login.html",
            local_admin_page_context(
                request=request,
                local_admin_username=state["username"],
                error=LOCAL_ADMIN_AUTH_ERROR,
            ),
            status_code=401,
        )

    logger.info(
        "Local break-glass admin login succeeded for %s from client=%s",
        state["username"],
        get_request_client_host(request) or "unknown",
    )
    redirect_target = LOCAL_ADMIN_ROTATE_PATH if local_admin_rotation_required(state) else "/admin/dashboard"
    return await issue_local_admin_session_response(request, state=state, redirect_url=redirect_target)


@app.get(LOCAL_ADMIN_ROTATE_PATH, response_class=HTMLResponse)
async def local_admin_rotate_password_page(
    request: Request,
    current_local_admin: Dict[str, Any] = Depends(get_current_local_admin_session_required),
):
    if not current_local_admin.get("rotation_required"):
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    csrf_token = get_or_create_local_admin_csrf_token(request)
    response = templates.TemplateResponse(
        request,
        "local_admin_rotate_password.html",
        {
            "request": request,
            "current_user": current_local_admin,
            "is_authenticated": False,
            "csrf_token": csrf_token,
        },
    )
    if not request.cookies.get(LOCAL_ADMIN_CSRF_COOKIE_NAME):
        response.set_cookie(
            LOCAL_ADMIN_CSRF_COOKIE_NAME,
            csrf_token,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            httponly=False,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            domain=settings.COOKIE_DOMAIN,
            path="/admin",
        )
    return response


@app.post(LOCAL_ADMIN_ROTATE_PATH)
async def local_admin_rotate_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(""),
    current_local_admin: Dict[str, Any] = Depends(get_local_admin_rotation_session_required),
):
    enforce_local_admin_csrf(request, form_token=csrf_token)

    if not new_password or len(new_password) < 16:
        return templates.TemplateResponse(
            request,
            "local_admin_rotate_password.html",
            {
                "request": request,
                "current_user": current_local_admin,
                "is_authenticated": False,
                "csrf_token": get_or_create_local_admin_csrf_token(request),
                "error": "Новый пароль должен быть не короче 16 символов.",
            },
            status_code=400,
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "local_admin_rotate_password.html",
            {
                "request": request,
                "current_user": current_local_admin,
                "is_authenticated": False,
                "csrf_token": get_or_create_local_admin_csrf_token(request),
                "error": "Подтверждение пароля не совпадает.",
            },
            status_code=400,
        )

    state = await load_local_admin_state(request)
    if state["username"] != current_local_admin["username"] or not local_admin_rotation_required(state):
        raise HTTPException(status_code=403, detail=LOCAL_ADMIN_ROTATION_REQUIRED_ERROR)

    updated_state = dict(state)
    updated_state["password_hash"] = build_local_admin_password_hash(new_password)
    updated_state["force_rotate"] = False
    updated_state["bootstrap_required"] = False
    updated_state["runtime_override"] = True
    updated_state["rotated_at"] = int(time.time())
    updated_state = await persist_local_admin_state(request, updated_state)
    await revoke_local_admin_session_token(request)
    logger.info(
        "Local break-glass admin password rotation completed for %s from client=%s",
        updated_state["username"],
        get_request_client_host(request) or "unknown",
    )
    return await issue_local_admin_session_response(request, state=updated_state, redirect_url="/admin/dashboard")


@app.post(LOCAL_ADMIN_LOGOUT_PATH)
async def local_admin_logout(
    request: Request,
    current_local_admin: Optional[Dict[str, Any]] = Depends(get_current_local_admin_session),
):
    if current_local_admin:
        enforce_local_admin_csrf(request)
        await revoke_local_admin_session_token(request)
        logger.info(
            "Local break-glass admin logout completed for %s from client=%s",
            current_local_admin["username"],
            get_request_client_host(request) or "unknown",
        )
    response = JSONResponse({"ok": True, "redirect": LOCAL_ADMIN_LOGIN_PATH})
    clear_local_admin_cookies(response)
    return response


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    thread_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    available_models = await request.app.state.llm_gateway.get_model_catalog()
    try:
        model_info = await resolve_runtime_model(current_user, available_models, request.app.state.llm_gateway)
    except LookupError:
        logger.error("Rendering chat page without active LLM models for user %s", current_user["username"])
        model_info = get_placeholder_model_info()
    current_user = {
        **current_user,
        "model": model_info["name"],
        "model_key": model_info["key"],
        "model_description": model_info["description"],
    }
    chat_store = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    threads = await load_thread_summaries(
        chat_store,
        current_user["username"],
        conversation_writer=conversation_writer,
    )
    resolved_thread_id = resolve_active_thread_id(thread_id, threads)
    history = await request.app.state.chat_store.get_history(current_user["username"], thread_id=resolved_thread_id)
    messages = prepare_messages(history)
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "messages": messages,
            "model_name": model_info["name"],
            "model_key": model_info["key"],
            "model_description": model_info["description"],
            "current_user": current_user,
            "is_authenticated": True,
            "thread_id": resolved_thread_id,
            "threads": threads,
        },
    )


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_admin_dashboard_identity_required),
):
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "is_authenticated": True,
            "home_href": current_user.get("home_href", "/chat"),
            "logout_path": current_user.get("logout_path", "/logout"),
            "csrf_cookie_name": current_user.get("csrf_cookie_name", "csrf_token"),
            "logout_redirect": current_user.get("logout_redirect", "/login"),
            "session_status_label": current_user.get("session_status_label", "Активен • Корпоративный доступ"),
            "dashboard_api_url": "/api/admin/dashboard/summary",
            "dashboard_live_api_url": "/api/admin/dashboard/live",
            "dashboard_history_api_url": "/api/admin/dashboard/history",
            "dashboard_events_api_url": "/api/admin/dashboard/events",
            "dashboard_refresh_interval_ms": ADMIN_DASHBOARD_REFRESH_INTERVAL_MS,
        },
    )


@app.get("/api/admin/dashboard/summary")
async def get_admin_dashboard_summary(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_admin_dashboard_identity_required),
):
    gateway: LLMGateway = request.app.state.llm_gateway
    payload = await build_admin_dashboard_summary(gateway)
    payload["current_user"] = current_user["username"]
    return JSONResponse(payload)


@app.get("/api/admin/dashboard/live")
async def get_admin_dashboard_live(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_admin_dashboard_identity_required),
):
    gateway: LLMGateway = request.app.state.llm_gateway
    payload = await gateway.get_dashboard_live_sample()
    if payload is None:
        summary = await build_admin_dashboard_summary(gateway)
        payload = sanitize_dashboard_live_sample(build_dashboard_live_sample(summary))
    response_payload = dict(payload or {})
    response_payload["current_user"] = current_user["username"]
    return JSONResponse(response_payload)


@app.get("/api/admin/dashboard/history")
async def get_admin_dashboard_history(
    request: Request,
    range: str = "24h",
    current_user: Dict[str, Any] = Depends(get_admin_dashboard_identity_required),
):
    gateway: LLMGateway = request.app.state.llm_gateway
    normalized_range = normalize_history_range(range)
    since_ts = int(time.time()) - HISTORY_RANGE_SECONDS[normalized_range]
    samples = await gateway.get_dashboard_history_samples(since_ts=since_ts)
    payload = build_dashboard_history_payload(samples, range_key=normalized_range)
    payload["current_user"] = current_user["username"]
    return JSONResponse(payload)


@app.get("/api/admin/dashboard/events")
async def get_admin_dashboard_events(
    request: Request,
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_admin_dashboard_identity_required),
):
    gateway: LLMGateway = request.app.state.llm_gateway
    payload = {
        "events": await gateway.get_dashboard_events(limit=limit),
        "current_user": current_user["username"],
    }
    return JSONResponse(payload)


@app.get("/api/user")
async def api_user(current_user: Dict[str, Any] = Depends(get_current_user_required)):
    return JSONResponse(current_user)


@app.get("/api/models")
async def get_available_models(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_required)):
    live_models = await asyncio.to_thread(settings.get_available_models)
    if not live_models:
        logger.error("No LLM models available for /api/models")
        return JSONResponse({"error": NO_LLM_MODELS_AVAILABLE_ERROR}, status_code=503)
    await request.app.state.llm_gateway.set_model_catalog(live_models)
    models = [
        {
            "key": key,
            "name": model_info.get("name", key),
            "description": model_info.get("description", "Без описания"),
            "size": model_info.get("size", "0"),
            "status": model_info.get("status", "active"),
        }
        for key, model_info in get_allowed_models_for_user(current_user, live_models).items()
    ]
    return JSONResponse(models)


@app.get("/api/threads")
async def get_chat_threads(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    chat_store = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    redis_threads = await load_thread_summaries(
        chat_store,
        current_user["username"],
        conversation_writer=conversation_writer,
    )
    threads = await resolve_thread_summaries_for_read_response(
        request,
        username=current_user["username"],
        redis_threads=redis_threads,
    )
    active_thread_id = resolve_active_thread_id(request.query_params.get("thread_id"), threads)
    return JSONResponse({"threads": threads, "active_thread_id": active_thread_id})


@app.post("/api/threads")
async def create_chat_thread(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    chat_store = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    created_thread_id = await conversation_writer.ensure_thread(
        current_user["username"],
        thread_id=f"thread-{uuid.uuid4().hex}",
    )
    threads = await load_thread_summaries(
        chat_store,
        current_user["username"],
        conversation_writer=conversation_writer,
    )
    thread = find_thread_summary(threads, created_thread_id)
    return JSONResponse(
        {
            "thread": thread,
            "threads": threads,
            "active_thread_id": created_thread_id,
        }
    )


@app.get("/api/threads/{thread_id}/messages")
async def get_chat_thread_messages(
    thread_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    chat_store = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    redis_threads = await load_thread_summaries(
        chat_store,
        current_user["username"],
        conversation_writer=conversation_writer,
    )
    threads = await resolve_thread_summaries_for_read_response(
        request,
        username=current_user["username"],
        redis_threads=redis_threads,
    )
    thread = find_thread_summary(threads, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    history = await chat_store.get_history(current_user["username"], thread_id=thread["id"])
    response_history = await resolve_thread_messages_for_read_response(
        request,
        username=current_user["username"],
        thread_id=thread["id"],
        redis_history=history,
    )
    return JSONResponse(
        {
            "thread": thread,
            "messages": prepare_messages(response_history),
            "thread_id": thread["id"],
        }
    )


@app.delete("/api/threads/{thread_id}")
async def delete_chat_thread(
    thread_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    try:
        payload = ThreadDeleteRequest(**await request.json())
    except Exception:
        payload = ThreadDeleteRequest()

    username = current_user["username"]
    normalized_thread_id = normalize_chat_thread_id(thread_id)
    requested_active_thread_id = normalize_chat_thread_id(payload.active_thread_id)
    chat_store = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)

    await conversation_writer.clear_thread(
        username,
        thread_id=normalized_thread_id,
        preserve_thread=False,
    )

    redis_threads = [serialize_thread_summary(thread) for thread in await chat_store.list_threads(username)]
    if not redis_threads:
        await conversation_writer.ensure_thread(
            username,
            thread_id=f"thread-{uuid.uuid4().hex}",
        )
        redis_threads = [serialize_thread_summary(thread) for thread in await chat_store.list_threads(username)]

    threads = await resolve_thread_summaries_for_read_response(
        request,
        username=username,
        redis_threads=redis_threads,
    )
    active_thread_id = resolve_active_thread_id(requested_active_thread_id, threads)
    return JSONResponse(
        {
            "ok": True,
            "thread_id": normalized_thread_id,
            "threads": threads,
            "active_thread_id": active_thread_id,
        }
    )


@app.post("/api/switch-model")
async def switch_user_model(
    request: Request,
    payload: ModelSwitchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    available_models = await asyncio.to_thread(settings.get_available_models)
    if not available_models:
        logger.error("No LLM models available for /api/switch-model")
        return JSONResponse({"error": NO_LLM_MODELS_AVAILABLE_ERROR}, status_code=503)
    await request.app.state.llm_gateway.set_model_catalog(available_models)
    allowed_models = get_allowed_models_for_user(current_user, available_models)
    new_model_key = payload.model.strip()
    if new_model_key not in allowed_models:
        return JSONResponse({"error": "Доступ к модели запрещен"}, status_code=403)

    model_info = allowed_models[new_model_key]
    updated_user = enrich_identity_session_fields(
        {
            **current_user,
            "model": model_info["name"],
            "model_description": model_info["description"],
            "model_key": new_model_key,
        },
        auth_source=current_user.get("auth_source", AUTH_SOURCE_PASSWORD),
    )
    access_token = create_access_token(
        build_token_payload(updated_user, "access"),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_access_token(
        build_token_payload(updated_user, "refresh"),
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    response = JSONResponse({"key": new_model_key, "name": model_info["name"], "description": model_info["description"]})
    set_auth_cookies(response, access_token, refresh_token, csrf_token=get_or_create_csrf_token(request))
    return response


@app.post("/api/refresh")
async def refresh_access_token(request: Request):
    enforce_csrf(request)
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return JSONResponse({"error": "No refresh token"}, status_code=401)

    token = extract_bearer_token(refresh_token)
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            return JSONResponse({"error": "Invalid refresh token"}, status_code=401)
        redis_client = getattr(request.app.state.llm_gateway, "redis", None)
        if redis_client is None:
            return JSONResponse({"error": AUTH_BACKEND_UNAVAILABLE_ERROR}, status_code=503)
        if await is_token_revoked(redis_client, payload):
            return JSONResponse({"error": "Invalid refresh token"}, status_code=401)

        current_user = enrich_identity_session_fields(
            {
                "username": payload.get("sub", ""),
                "canonical_principal": payload.get("canonical_principal"),
                "display_name": payload.get("display_name", payload.get("sub", "")),
                "email": payload.get("email", f"{payload.get('sub', '')}@{settings.LDAP_DOMAIN}"),
                "groups": payload.get("groups", []),
                "model": payload.get("model", settings.DEFAULT_MODEL or "phi3:mini"),
                "model_description": payload.get("model_description", "Модель по умолчанию"),
                "model_key": payload.get("model_key", payload.get("model", settings.DEFAULT_MODEL or "phi3:mini")),
                "auth_source": payload.get("auth_source"),
                "auth_time": payload.get("auth_time"),
                "directory_checked_at": payload.get("directory_checked_at"),
                "identity_version": payload.get("identity_version"),
            },
            auth_source=AUTH_SOURCE_PASSWORD,
        )
        if not current_user["username"]:
            return JSONResponse({"error": "Invalid refresh token"}, status_code=401)

        access_token = create_access_token(
            build_token_payload(current_user, "access"),
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        rotated_refresh_token = create_access_token(
            build_token_payload(current_user, "refresh"),
            expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await revoke_token(redis_client, refresh_token)
        response = Response(status_code=204)
        set_auth_cookies(
            response,
            access_token,
            rotated_refresh_token,
            csrf_token=get_or_create_csrf_token(request),
        )
        return response
    except JWTError:
        return JSONResponse({"error": "Invalid refresh token"}, status_code=401)


@app.post("/api/chat")
async def api_chat(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_required)):
    enforce_csrf(request)
    await request.app.state.rate_limiter.check(current_user["username"])

    try:
        payload = PromptRequest(**await request.json())
    except Exception:
        return JSONResponse({"error": "Invalid request format"}, status_code=400)

    prompt = filter_prompt_injection(payload.prompt.strip())
    requested_model = (payload.model or "").strip() or None
    thread_id = normalize_chat_thread_id(payload.thread_id)
    if not prompt:
        return JSONResponse({"error": "Пустой запрос"}, status_code=400)

    gateway: LLMGateway = request.app.state.llm_gateway
    chat_store: AsyncChatStore = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    queue_pressure = await gateway.get_queue_pressure()
    if queue_pressure["queue_depth"] >= queue_pressure["threshold"]:
        return JSONResponse({"error": "Сервис перегружен", "retry_after": 5}, status_code=503)

    username = current_user["username"]
    available_models = await gateway.get_model_catalog()
    if not available_models:
        logger.error("No LLM models available for chat request from user %s", username)
        return JSONResponse({"error": NO_LLM_MODELS_AVAILABLE_ERROR}, status_code=503)
    try:
        model_info = await resolve_runtime_model(current_user, available_models, gateway, requested_model=requested_model)
    except LookupError as exc:
        message = str(exc) or "LLM model not found"
        logger.error(
            "Chat request rejected for user %s: requested_model=%s error=%s",
            username,
            requested_model or current_user.get("model_key") or current_user.get("model") or "unknown",
            message,
        )
        return JSONResponse(
            {"error": message},
            status_code=503 if message == NO_LLM_MODELS_AVAILABLE_ERROR else 404,
        )
    logger.info(
        "Chat request accepted for user %s with requested_model=%s resolved_model=%s prompt_size=%s file_count=%s",
        username,
        requested_model or current_user.get("model_key") or current_user.get("model") or "unknown",
        model_info["key"],
        len(prompt),
        0,
    )
    original_history = await chat_store.get_history(username, thread_id=thread_id)
    history = apply_history_budget(original_history)
    logger.info(
        "Context governance for user %s: original_history_count=%s trimmed_history_count=%s budget_applied=%s",
        username,
        len(original_history),
        len(history),
        "yes" if history != original_history else "no",
    )
    job_id = await gateway.enqueue_job(
        username=username,
        thread_id=thread_id,
        model_key=model_info["key"],
        model_name=model_info["name"],
        prompt=prompt,
        history=history,
    )
    await conversation_writer.append_message(username, "user", prompt, thread_id=thread_id)

    async def event_stream():
        try:
            yield f"data: {json.dumps({'job_id': job_id}, ensure_ascii=False)}\n\n"
            async for event in gateway.stream_events(job_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            await gateway.cancel_job(job_id, username=username)
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat_with_files")
async def api_chat_with_files(
    request: Request,
    message: str = Form(""),
    model: Optional[str] = Form(None),
    thread_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    await request.app.state.rate_limiter.check(current_user["username"])

    prompt = filter_prompt_injection(message.strip())
    requested_model = (model or "").strip() or None
    thread_id = normalize_chat_thread_id(thread_id)

    gateway: LLMGateway = request.app.state.llm_gateway
    chat_store: AsyncChatStore = request.app.state.chat_store
    conversation_writer = build_conversation_writer(request.app.state)
    queue_pressure = await gateway.get_queue_pressure()
    if queue_pressure["queue_depth"] >= queue_pressure["threshold"]:
        return JSONResponse({"error": "Сервис перегружен", "retry_after": 5}, status_code=503)

    username = current_user["username"]
    available_models = await gateway.get_model_catalog()
    if not available_models:
        logger.error("No LLM models available for file chat request from user %s", username)
        return JSONResponse({"error": NO_LLM_MODELS_AVAILABLE_ERROR}, status_code=503)
    try:
        model_info = await resolve_runtime_model(current_user, available_models, gateway, requested_model=requested_model)
    except LookupError as exc:
        message_text = str(exc) or "LLM model not found"
        logger.error(
            "File chat request rejected for user %s: requested_model=%s error=%s",
            username,
            requested_model or current_user.get("model_key") or current_user.get("model") or "unknown",
            message_text,
        )
        return JSONResponse(
            {"error": message_text},
            status_code=503 if message_text == NO_LLM_MODELS_AVAILABLE_ERROR else 404,
        )

    temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    staged_files: list[dict[str, Any]] = []
    staging_ms = 0
    parse_ms = 0
    original_doc_chars = 0
    trimmed_doc_chars = 0
    staging_started = perf_counter()
    try:
        if settings.ENABLE_PARSER_PUBLIC_CUTOVER:
            if not settings.ENABLE_PARSER_STAGE:
                raise RuntimeError("Parser stage is disabled")

            staged_request = await stage_uploads_for_parser(files, username=username)
            staging_ms = elapsed_ms(staging_started)
            staged_files = list(staged_request.get("files") or [])
            original_history = await chat_store.get_history(username, thread_id=thread_id)
            history = apply_history_budget(original_history)
            history_entry = (
                f"{prompt or 'Пользователь не уточнил задачу'}\n\n"
                f"[Вложения: {', '.join(file_info['name'] for file_info in staged_files)}]"
            )
            log_file_parse_observability(
                username=username,
                job_kind=JOB_KIND_PARSE,
                file_count=len(staged_files),
                staging_ms=staging_ms,
                parse_ms=0,
                original_doc_chars=0,
                trimmed_doc_chars=0,
                terminal_status="accepted",
                error_type=ERROR_TYPE_NONE,
            )
            logger.info(
                "File chat public cutover request accepted for user %s with %s files and parser root job model %s",
                username,
                len(staged_files),
                model_info["key"],
            )

            if wants_event_stream(request):
                job_id = await enqueue_parser_public_job(
                    gateway=gateway,
                    conversation_writer=conversation_writer,
                    username=username,
                    thread_id=thread_id,
                    model_info=model_info,
                    message=prompt,
                    history=history,
                    history_entry=history_entry,
                    staging_id=staged_request["staging_id"],
                    staged_files=staged_files,
                    requested_model=requested_model,
                )

                async def event_stream():
                    try:
                        yield f"data: {json.dumps({'job_id': job_id}, ensure_ascii=False)}\n\n"
                        async for event in gateway.stream_events(job_id):
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except asyncio.CancelledError:
                        await gateway.cancel_job(job_id, username=username)
                        raise

                return StreamingResponse(
                    event_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

            job_id, result = await run_parser_public_job(
                gateway=gateway,
                conversation_writer=conversation_writer,
                username=username,
                thread_id=thread_id,
                model_info=model_info,
                message=prompt,
                history=history,
                history_entry=history_entry,
                staging_id=staged_request["staging_id"],
                staged_files=staged_files,
                requested_model=requested_model,
            )
            status = result.get("status")
            if status == "completed":
                response_text = normalize_document_response((result.get("result") or "").strip())
                return JSONResponse(
                    {
                        "response": response_text or DOCUMENT_UNCLEAR_REQUEST_RESPONSE,
                        "files": [{"name": file_info["name"], "size": file_info["size"]} for file_info in staged_files],
                        "job_id": job_id,
                    }
                )
            if status == "failed":
                await restore_chat_history(conversation_writer, username, thread_id, history)
                return JSONResponse({"error": result.get("error") or "Сервис временно недоступен"}, status_code=503)
            if status == "cancelled":
                await restore_chat_history(conversation_writer, username, thread_id, history)
                return JSONResponse({"error": "Генерация была отменена"}, status_code=409)
            await restore_chat_history(conversation_writer, username, thread_id, history)
            return JSONResponse({"error": "Истекло время ожидания ответа модели"}, status_code=504)

        temp_dir, staged_files = await stage_uploads(files, username=username)
        staging_ms = elapsed_ms(staging_started)
        parse_started = perf_counter()
        extracted_documents = await asyncio.to_thread(extract_documents_from_staging, staged_files)
        parse_ms = elapsed_ms(parse_started)
        budgeted_documents = apply_document_budget(extracted_documents)
        logger.info(
            "Parsed uploaded documents for user %s: %s",
            username,
            [
                {
                    "name": document["name"],
                    "chars": len(document["content"]),
                    "empty": not bool(document["content"].strip()),
                }
                for document in extracted_documents
            ],
        )
        original_history = await chat_store.get_history(username, thread_id=thread_id)
        history = apply_history_budget(original_history)
        original_doc_chars = sum(len((document.get("content") or "").strip()) for document in extracted_documents)
        trimmed_doc_chars = sum(len((document.get("content") or "").strip()) for document in budgeted_documents)
        log_file_parse_observability(
            username=username,
            job_kind=JOB_KIND_FILE_CHAT,
            file_count=len(staged_files),
            staging_ms=staging_ms,
            parse_ms=parse_ms,
            original_doc_chars=original_doc_chars,
            trimmed_doc_chars=trimmed_doc_chars,
            terminal_status="success",
            error_type=ERROR_TYPE_NONE,
        )
        logger.info(
            "Document context governance for user %s: original_history_count=%s trimmed_history_count=%s original_doc_chars=%s trimmed_doc_chars=%s budget_applied=%s",
            username,
            len(original_history),
            len(history),
            original_doc_chars,
            trimmed_doc_chars,
            "yes" if history != original_history or trimmed_doc_chars != original_doc_chars else "no",
        )
        final_prompt = build_document_prompt(prompt, budgeted_documents)
        logger.info(
            "Document final prompt for user %s: chars=%s approx_tokens=%s file_count=%s",
            username,
            len(final_prompt),
            approximate_token_count(final_prompt),
            len(staged_files),
        )
        logger.info(
            "File chat request accepted for user %s with %s files and model %s",
            username,
            len(staged_files),
            model_info["key"],
        )
        history_entry = (
            f"{prompt or 'Пользователь не уточнил задачу'}\n\n"
            f"[Вложения: {', '.join(file_info['name'] for file_info in staged_files)}]"
        )
        retry_prompt = build_retry_document_prompt(prompt, budgeted_documents)
        file_chat_metadata = build_file_chat_job_metadata(
            retry_prompt=retry_prompt,
            staged_files=staged_files,
            doc_chars=trimmed_doc_chars,
            thread_id=thread_id,
        )
        temp_dir.cleanup()
        temp_dir = None
        if wants_event_stream(request):
            job_id = await enqueue_document_job(
                gateway=gateway,
                conversation_writer=conversation_writer,
                username=username,
                thread_id=thread_id,
                model_info=model_info,
                prompt=final_prompt,
                history=history,
                history_entry=history_entry,
                file_chat=file_chat_metadata,
            )

            async def event_stream():
                try:
                    yield f"data: {json.dumps({'job_id': job_id}, ensure_ascii=False)}\n\n"
                    async for event in gateway.stream_events(job_id):
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.CancelledError:
                    await gateway.cancel_job(job_id, username=username)
                    raise

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        job_id, result = await run_document_job(
            gateway=gateway,
            conversation_writer=conversation_writer,
            username=username,
            thread_id=thread_id,
            model_info=model_info,
            prompt=final_prompt,
            history=history,
            history_entry=history_entry,
            file_chat=file_chat_metadata,
        )
        status = result.get("status")
        if status == "completed":
            response_text = (result.get("result") or "").strip()
            if response_requires_document_retry(response_text):
                logger.warning(
                    "Document response retry triggered for user %s job %s due to inaccessible-file phrasing",
                    username,
                    job_id,
                )
                await restore_chat_history(conversation_writer, username, thread_id, history)
                retry_prompt = build_retry_document_prompt(prompt, budgeted_documents)
                retry_job_id, retry_result = await run_document_job(
                    gateway=gateway,
                    conversation_writer=conversation_writer,
                    username=username,
                    thread_id=thread_id,
                    model_info=model_info,
                    prompt=retry_prompt,
                    history=history,
                    history_entry=history_entry,
                    file_chat=file_chat_metadata,
                )
                if retry_result.get("status") == "completed":
                    response_text = (retry_result.get("result") or "").strip()
                    job_id = retry_job_id
                else:
                    await restore_chat_history(conversation_writer, username, thread_id, history)
                    return JSONResponse({"error": retry_result.get("error") or "Сервис временно недоступен"}, status_code=503)

            if response_requires_document_retry(response_text):
                logger.warning(
                    "Document safeguard fallback applied for user %s job %s after retry",
                    username,
                    job_id,
                )
                response_text = DOCUMENT_NO_INFORMATION_RESPONSE
                await restore_chat_history(conversation_writer, username, thread_id, history)
                await conversation_writer.append_message(username, "user", history_entry, thread_id=thread_id)
                await conversation_writer.append_message(username, "assistant", response_text, thread_id=thread_id)

            response_text = normalize_document_response(response_text)
            return JSONResponse(
                {
                    "response": response_text or DOCUMENT_UNCLEAR_REQUEST_RESPONSE,
                    "files": [{"name": file_info["name"], "size": file_info["size"]} for file_info in staged_files],
                    "job_id": job_id,
                }
            )
        if status == "failed":
            await restore_chat_history(conversation_writer, username, thread_id, history)
            return JSONResponse({"error": result.get("error") or "Сервис временно недоступен"}, status_code=503)
        if status == "cancelled":
            await restore_chat_history(conversation_writer, username, thread_id, history)
            return JSONResponse({"error": "Генерация была отменена"}, status_code=409)
        await restore_chat_history(conversation_writer, username, thread_id, history)
        return JSONResponse({"error": "Истекло время ожидания ответа модели"}, status_code=504)
    except HTTPException:
        log_file_parse_observability(
            username=username,
            job_kind=JOB_KIND_FILE_CHAT,
            file_count=len(staged_files) or len(files),
            staging_ms=staging_ms or elapsed_ms(staging_started),
            parse_ms=parse_ms,
            original_doc_chars=original_doc_chars,
            trimmed_doc_chars=trimmed_doc_chars,
            terminal_status="failed",
            error_type=classify_observability_error(phase="validation", default=ERROR_TYPE_VALIDATION),
        )
        raise
    except ValueError as exc:
        log_file_parse_observability(
            username=username,
            job_kind=JOB_KIND_FILE_CHAT,
            file_count=len(staged_files) or len(files),
            staging_ms=staging_ms or elapsed_ms(staging_started),
            parse_ms=parse_ms,
            original_doc_chars=original_doc_chars,
            trimmed_doc_chars=trimmed_doc_chars,
            terminal_status="failed",
            error_type=classify_observability_error(str(exc), phase="validation", default=ERROR_TYPE_VALIDATION),
        )
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        log_file_parse_observability(
            username=username,
            job_kind=JOB_KIND_FILE_CHAT,
            file_count=len(staged_files) or len(files),
            staging_ms=staging_ms or elapsed_ms(staging_started),
            parse_ms=parse_ms,
            original_doc_chars=original_doc_chars,
            trimmed_doc_chars=trimmed_doc_chars,
            terminal_status="failed",
            error_type=classify_observability_error(str(exc), phase="parse", default=ERROR_TYPE_PARSE),
        )
        logger.warning("File parsing failed for user %s: %s", username, exc)
        return JSONResponse({"error": str(exc)}, status_code=503)
    except Exception:
        log_file_parse_observability(
            username=username,
            job_kind=JOB_KIND_FILE_CHAT,
            file_count=len(staged_files) or len(files),
            staging_ms=staging_ms or elapsed_ms(staging_started),
            parse_ms=parse_ms,
            original_doc_chars=original_doc_chars,
            trimmed_doc_chars=trimmed_doc_chars,
            terminal_status="failed",
            error_type=classify_observability_error("internal_error", default=ERROR_TYPE_INTERNAL),
        )
        logger.exception("Unhandled file chat error for user %s", username)
        return JSONResponse({"error": "Не удалось обработать вложения"}, status_code=500)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


@app.post("/api/chat/cancel/{job_id}")
async def cancel_chat(job_id: str, request: Request, current_user: Dict[str, Any] = Depends(get_current_user_required)):
    enforce_csrf(request)
    cancelled = await request.app.state.llm_gateway.cancel_job(job_id, username=current_user["username"])
    return JSONResponse({"ok": cancelled})


@app.post("/api/chat/clear")
async def clear_chat(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_required)):
    enforce_csrf(request)
    requested_thread_id: Optional[str] = request.query_params.get("thread_id")
    if requested_thread_id is None:
        try:
            payload = ThreadScopedRequest(**await request.json())
        except Exception:
            payload = ThreadScopedRequest()
        requested_thread_id = payload.thread_id
    thread_id = normalize_chat_thread_id(requested_thread_id)
    conversation_writer = build_conversation_writer(request.app.state)
    await conversation_writer.clear_thread(current_user["username"], thread_id=thread_id)
    return JSONResponse({"ok": True, "thread_id": thread_id})


@app.post("/api/render-markdown")
async def api_render_markdown(
    request: Request,
    payload: MarkdownRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    return JSONResponse({"html": render_markdown(payload.text)})


@app.post("/debug/load")
async def debug_load(
    request: Request,
    n: int = 5,
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    if not settings.DEBUG_LOAD_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    if not user_is_admin(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    enforce_csrf(request)
    gateway: LLMGateway = request.app.state.llm_gateway
    available_models = await gateway.get_model_catalog()
    if not available_models:
        return JSONResponse({"error": NO_LLM_MODELS_AVAILABLE_ERROR}, status_code=503)
    model_info = await resolve_runtime_model(current_user, available_models, gateway)
    total = max(1, min(n, settings.DEBUG_LOAD_MAX_TASKS))

    async def run_one(index: int) -> tuple[bool, float, str]:
        started = perf_counter()
        try:
            job_id = await gateway.enqueue_job(
                username=current_user["username"],
                model_key=model_info["key"],
                model_name=model_info["name"],
                prompt=f"debug-load-{index}",
                history=[],
                workload_class="chat",
                priority="p1",
            )
            result = await wait_for_terminal_job(gateway, job_id, settings.DEBUG_LOAD_TIMEOUT_SECONDS)
            latency = perf_counter() - started
            return result.get("status") == "completed", latency, result.get("status", "unknown")
        except Exception:
            latency = perf_counter() - started
            return False, latency, "error"

    results = await asyncio.gather(*(run_one(index) for index in range(total)))
    success = sum(1 for ok, _, _ in results if ok)
    fail = total - success
    avg_latency = sum(latency for _, latency, _ in results) / max(total, 1)
    return JSONResponse(
        {
            "requested": total,
            "success": success,
            "fail": fail,
            "avg_latency_seconds": round(avg_latency, 3),
            "statuses": [status for _, _, status in results],
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.APP_RELOAD)









import asyncio
import json
import logging
import re
import secrets
import time
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import timedelta
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
from llm_gateway import (
    AsyncChatStore,
    AsyncRateLimiter,
    classify_observability_error,
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
from parser_stage import stage_uploads_to_shared_root

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
MAX_UPLOAD_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_FILES = 10
GENERIC_UPLOAD_CONTENT_TYPES = {"", "application/octet-stream"}
ALLOWED_UPLOAD_MIME_TYPES: dict[str, set[str]] = {
    ".txt": {"text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}
MAX_DOCUMENT_CHARS = 12_000
MAX_PARSED_DOCUMENT_CHARS = MAX_DOCUMENT_CHARS
MAX_PDF_PAGES = 20
IMAGE_OCR_MAX_DIMENSION = 2000
DOCUMENT_TRUNCATION_MARKER = "[DOCUMENT_TRUNCATED]"
UPLOAD_UNSUPPORTED_TYPE_ERROR = "Поддерживаются только TXT, PDF, DOCX, PNG, JPG и JPEG."
DOCUMENT_NO_INFORMATION_RESPONSE = "В предоставленных документах нет информации для ответа на этот вопрос."
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


class PromptRequest(BaseModel):
    prompt: str
    model: Optional[str] = None


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


def sanitize_upload_filename(filename: str) -> str:
    candidate = Path(filename or "upload.bin").name
    extension = Path(candidate).suffix.lower()
    stem = Path(candidate).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "upload"
    safe_extension = re.sub(r"[^a-z0-9.]+", "", extension) or ".bin"
    safe_stem = safe_stem[:80]
    return f"{uuid.uuid4().hex[:12]}-{safe_stem}{safe_extension}"


def detect_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def normalize_upload_content_type(content_type: Optional[str]) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def upload_content_type_is_allowed(extension: str, content_type: Optional[str]) -> bool:
    allowed_content_types = ALLOWED_UPLOAD_MIME_TYPES.get(extension)
    if not allowed_content_types:
        return False

    normalized_content_type = normalize_upload_content_type(content_type)
    if normalized_content_type in GENERIC_UPLOAD_CONTENT_TYPES:
        return True

    return normalized_content_type in allowed_content_types


def log_upload_rejection(
    *,
    reason: str,
    safe_name: str,
    extension: str,
    content_type: Optional[str],
    username: Optional[str],
) -> None:
    logger.warning(
        "upload_rejected reason=%s filename=%s extension=%s content_type=%s username=%s",
        reason,
        safe_name,
        extension,
        normalize_upload_content_type(content_type) or "application/octet-stream",
        (username or "").strip() or "unknown",
    )


def extract_text_from_txt(path: Path) -> str:
    chunks = []
    consumed = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        while consumed < MAX_PARSED_DOCUMENT_CHARS:
            chunk = handle.read(min(4096, MAX_PARSED_DOCUMENT_CHARS - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
    return "".join(chunks)


def extract_text_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    text_chunks = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            text_chunks.append(node.text)
        elif node.tag.endswith("}p"):
            text_chunks.append("\n")
    return "".join(text_chunks).strip()


def extract_text_from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES]).strip()
    except ImportError:
        try:
            import fitz  # type: ignore

            document = fitz.open(path)
            try:
                page_count = min(len(document), MAX_PDF_PAGES)
                return "\n".join(document[index].get_text() for index in range(page_count)).strip()
            finally:
                document.close()
        except ImportError as exc:
            raise RuntimeError("PDF parser unavailable on server") from exc


def extract_text_from_image(path: Path) -> str:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError("OCR parser unavailable on server") from exc

    with Image.open(path) as image:
        image.thumbnail((IMAGE_OCR_MAX_DIMENSION, IMAGE_OCR_MAX_DIMENSION))
        return pytesseract.image_to_string(image).strip()


def parse_uploaded_file(path: Path) -> str:
    extension = detect_extension(path.name)
    if extension == ".txt":
        return extract_text_from_txt(path)
    if extension == ".docx":
        return extract_text_from_docx(path)
    if extension == ".pdf":
        return extract_text_from_pdf(path)
    if extension in {".png", ".jpg", ".jpeg"}:
        return extract_text_from_image(path)
    raise ValueError(UPLOAD_UNSUPPORTED_TYPE_ERROR)


def build_document_prompt(message: str, extracted_documents: list[dict[str, str]]) -> str:
    return _build_document_prompt(message, extracted_documents, force_documents=False)


def apply_document_budget(extracted_documents: list[dict[str, str]]) -> list[dict[str, str]]:
    budgeted_documents: list[dict[str, str]] = []
    consumed_chars = 0

    for document in extracted_documents:
        name = (document.get("name") or "").strip() or "document"
        content = (document.get("content") or "").strip()
        if not content:
            continue

        remaining = MAX_DOCUMENT_CHARS - consumed_chars
        if remaining <= 0:
            budgeted_documents.append({"name": name, "content": DOCUMENT_TRUNCATION_MARKER})
            continue

        if len(content) > remaining:
            marker = f"\n{DOCUMENT_TRUNCATION_MARKER}"
            snippet_limit = max(0, remaining - len(marker))
            snippet = content[:snippet_limit].rstrip()
            content = f"{snippet}{marker}" if snippet else DOCUMENT_TRUNCATION_MARKER

        consumed_chars += len(content)
        budgeted_documents.append({"name": name, "content": content})

    return budgeted_documents


def _build_document_prompt(
    message: str,
    extracted_documents: list[dict[str, str]],
    *,
    force_documents: bool,
) -> str:
    document_chunks = []
    budgeted_documents = apply_document_budget(extracted_documents)

    for index, document in enumerate(budgeted_documents, start=1):
        content = document["content"].strip()
        if not content:
            continue
        document_chunks.append(f"[Документ {index}: {document['name']}]\n{content}")

    if not document_chunks:
        raise ValueError("Не удалось извлечь текст из выбранных файлов")

    document_block = "\n\n".join(document_chunks)
    request_text = message.strip() or "Пользователь не уточнил задачу"
    extra_guard = ""
    if force_documents:
        extra_guard = (
            "\n# ДОПОЛНИТЕЛЬНОЕ ТРЕБОВАНИЕ\n"
            "Текст документов уже передан тебе ниже. "
            "Нельзя говорить, что у тебя нет доступа к файлам, документам или вложениям. "
            "Если фактов недостаточно, верни только точную фразу:\n"
            f"\"{DOCUMENT_NO_INFORMATION_RESPONSE}\"\n"
        )

    return f"""
Ты — корпоративный AI-ассистент.

---

# КРИТИЧЕСКОЕ ПРАВИЛО

Ты НЕ имеешь права выдумывать информацию.

---

# РАБОТА С ДОКУМЕНТАМИ

- Документы уже загружены.
- Их текст приведён ниже.
- Блок ДОКУМЕНТЫ ниже — это уже извлечённое буквальное содержимое файлов.
- Это твой ЕДИНСТВЕННЫЙ источник данных.
- Отвечай как корпоративный аналитик: кратко, точно, по существу.

---

# ЗАПРЕЩЕНО

- говорить, что у тебя нет доступа к файлам
- игнорировать документы
- придумывать факты, цифры, даты, имена, выводы
- дополнять ответ предположениями
- использовать фразы вроде "скорее всего", если этого нет в тексте

---

# ЕСЛИ ДАННЫХ НЕТ

Ответь ровно так:
"{DOCUMENT_NO_INFORMATION_RESPONSE}"

---

# ПОВЕДЕНИЕ

- Если вопрос пользователя конкретный: ответь только по документам.
- Если пользователь спрашивает "что в файле", "что в документе" или просит показать содержимое, передай содержание прямо по тексту документа без выдумок.
- Если запрос пустой или неясный: предложи один из вариантов действий кратким списком.
- Если документы противоречат друг другу: прямо укажи на противоречие и не делай догадок.
{extra_guard}
---

# ДОКУМЕНТЫ

{document_block}

---

# ЗАПРОС ПОЛЬЗОВАТЕЛЯ

{request_text}
""".strip()


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


async def restore_chat_history(chat_store: AsyncChatStore, username: str, history: list[dict[str, Any]]) -> None:
    await chat_store.clear_history(username)
    for message in history:
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            await chat_store.append_message(username, role, content)


async def run_document_job(
    *,
    gateway: LLMGateway,
    chat_store: AsyncChatStore,
    username: str,
    model_info: Dict[str, str],
    prompt: str,
    history: list[dict[str, Any]],
    history_entry: str,
    file_chat: Optional[dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any]]:
    job_id = await enqueue_document_job(
        gateway=gateway,
        chat_store=chat_store,
        username=username,
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
    chat_store: AsyncChatStore,
    username: str,
    model_info: Dict[str, str],
    prompt: str,
    history: list[dict[str, Any]],
    history_entry: str,
    file_chat: Optional[dict[str, Any]] = None,
) -> str:
    limited_history = apply_history_budget(history)
    job_id = await gateway.enqueue_job(
        username=username,
        model_key=model_info["key"],
        model_name=model_info["name"],
        prompt=prompt,
        history=limited_history,
        job_kind=JOB_KIND_FILE_CHAT,
        file_chat=file_chat,
    )
    await chat_store.append_message(username, "user", history_entry)
    return job_id


async def stage_uploads_for_parser(
    files: list[UploadFile],
    *,
    username: Optional[str] = None,
) -> dict[str, Any]:
    return await stage_uploads_to_shared_root(
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
    chat_store: AsyncChatStore,
    username: str,
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
        chat_store=chat_store,
        username=username,
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
    chat_store: AsyncChatStore,
    username: str,
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
        model_info=model_info,
        message=message,
        history=history,
        staging_id=staging_id,
        staged_files=staged_files,
        requested_model=requested_model,
    )
    await chat_store.append_message(username, "user", history_entry)
    return job_id


async def stage_uploads(
    files: list[UploadFile],
    *,
    username: Optional[str] = None,
) -> tuple[tempfile.TemporaryDirectory[str], list[dict[str, Any]]]:
    if not files:
        raise HTTPException(status_code=400, detail="Не выбраны файлы")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"Максимум файлов за запрос: {MAX_UPLOAD_FILES}")

    temp_dir = tempfile.TemporaryDirectory(prefix="ai-agent-upload-")
    staged_files: list[dict[str, Any]] = []
    try:
        for upload in files:
            safe_name = sanitize_upload_filename(upload.filename or "upload.bin")
            display_name = Path(upload.filename or safe_name).name or safe_name
            suffix = detect_extension(safe_name)
            normalized_content_type = normalize_upload_content_type(upload.content_type)
            if suffix not in ALLOWED_UPLOAD_MIME_TYPES:
                log_upload_rejection(
                    reason="unsupported_extension",
                    safe_name=safe_name,
                    extension=suffix or "<none>",
                    content_type=normalized_content_type,
                    username=username,
                )
                raise HTTPException(status_code=400, detail=UPLOAD_UNSUPPORTED_TYPE_ERROR)
            if not upload_content_type_is_allowed(suffix, normalized_content_type):
                log_upload_rejection(
                    reason="content_type_mismatch",
                    safe_name=safe_name,
                    extension=suffix,
                    content_type=normalized_content_type,
                    username=username,
                )
                raise HTTPException(status_code=400, detail=UPLOAD_UNSUPPORTED_TYPE_ERROR)

            target_path = Path(temp_dir.name) / safe_name
            size = 0
            with target_path.open("wb") as target:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_FILE_SIZE_BYTES:
                        log_upload_rejection(
                            reason="file_too_large",
                            safe_name=safe_name,
                            extension=suffix,
                            content_type=normalized_content_type,
                            username=username,
                        )
                        raise HTTPException(status_code=413, detail=f"Файл {safe_name} превышает лимит 50 MB")
                    target.write(chunk)

            staged_files.append(
                {
                    "name": display_name,
                    "safe_name": safe_name,
                    "path": target_path,
                    "size": size,
                    "content_type": normalized_content_type or "application/octet-stream",
                }
            )
    except Exception:
        temp_dir.cleanup()
        raise
    finally:
        for upload in files:
            await upload.close()

    return temp_dir, staged_files


def extract_documents_from_staging(staged_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    for file_info in staged_files:
        text = parse_uploaded_file(file_info["path"])
        extracted.append({"name": file_info["name"], "content": text})
    return extracted


def log_file_parse_observability(
    *,
    username: str,
    file_count: int,
    staging_ms: int,
    parse_ms: int,
    original_doc_chars: int,
    trimmed_doc_chars: int,
    terminal_status: str,
    error_type: str,
) -> None:
    log_method = logger.info if terminal_status == "success" else logger.warning
    log_method(
        "file_parse_observability username=%s job_kind=%s file_count=%s staging_ms=%s parse_ms=%s "
        "original_doc_chars=%s trimmed_doc_chars=%s terminal_status=%s error_type=%s",
        username,
        JOB_KIND_FILE_CHAT,
        file_count,
        staging_ms,
        parse_ms,
        original_doc_chars,
        trimmed_doc_chars,
        terminal_status,
        error_type,
    )


def build_file_chat_job_metadata(
    *,
    retry_prompt: Optional[str],
    staged_files: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "retry_prompt": (retry_prompt or "").strip() or None,
        "suppress_token_stream": True,
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


def build_login_rate_subject(request: Request, username: str) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    real_ip = request.headers.get("x-real-ip", "")
    client_host = real_ip or (forwarded_for.split(",", 1)[0].strip() if forwarded_for else "")
    if not client_host:
        client_host = request.client.host if request.client and request.client.host else "unknown"
    normalized = normalize_username(username) or username.strip().lower() or "anonymous"
    return f"{client_host}:{normalized[:128]}"


def user_is_admin(user_info: Dict[str, Any]) -> bool:
    groups = [group.lower() for group in user_info.get("groups", [])]
    return any(
        group in {"domain admins", "admins", "administrators", "ai-admins", "ai-admin"}
        or group.endswith("-admins")
        or "admin" in group
        for group in groups
    )


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
    return trusted_proxy_sso_enabled() and get_request_method(request) == "GET" and get_request_path(request) == settings.SSO_LOGIN_PATH


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
    try:
        yield
    finally:
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
    reject_untrusted_auth_proxy_headers(request)
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


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_required)):
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
    history = await request.app.state.chat_store.get_history(current_user["username"])
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
        },
    )


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
    if not prompt:
        return JSONResponse({"error": "Пустой запрос"}, status_code=400)

    gateway: LLMGateway = request.app.state.llm_gateway
    chat_store: AsyncChatStore = request.app.state.chat_store
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
    original_history = await chat_store.get_history(username)
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
        model_key=model_info["key"],
        model_name=model_info["name"],
        prompt=prompt,
        history=history,
    )
    await chat_store.append_message(username, "user", prompt)

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
    files: list[UploadFile] = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user_required),
):
    enforce_csrf(request)
    await request.app.state.rate_limiter.check(current_user["username"])

    prompt = filter_prompt_injection(message.strip())
    requested_model = (model or "").strip() or None

    gateway: LLMGateway = request.app.state.llm_gateway
    chat_store: AsyncChatStore = request.app.state.chat_store
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
            original_history = await chat_store.get_history(username)
            history = apply_history_budget(original_history)
            history_entry = (
                f"{prompt or 'Пользователь не уточнил задачу'}\n\n"
                f"[Вложения: {', '.join(file_info['name'] for file_info in staged_files)}]"
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
                    chat_store=chat_store,
                    username=username,
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
                chat_store=chat_store,
                username=username,
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
                await restore_chat_history(chat_store, username, history)
                return JSONResponse({"error": result.get("error") or "Сервис временно недоступен"}, status_code=503)
            if status == "cancelled":
                await restore_chat_history(chat_store, username, history)
                return JSONResponse({"error": "Генерация была отменена"}, status_code=409)
            await restore_chat_history(chat_store, username, history)
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
        original_history = await chat_store.get_history(username)
        history = apply_history_budget(original_history)
        original_doc_chars = sum(len((document.get("content") or "").strip()) for document in extracted_documents)
        trimmed_doc_chars = sum(len((document.get("content") or "").strip()) for document in budgeted_documents)
        log_file_parse_observability(
            username=username,
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
        final_prompt = _build_document_prompt(prompt, budgeted_documents, force_documents=False)
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
        retry_prompt = _build_document_prompt(prompt, budgeted_documents, force_documents=True)
        file_chat_metadata = build_file_chat_job_metadata(
            retry_prompt=retry_prompt,
            staged_files=staged_files,
        )
        temp_dir.cleanup()
        temp_dir = None
        if wants_event_stream(request):
            job_id = await enqueue_document_job(
                gateway=gateway,
                chat_store=chat_store,
                username=username,
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
            chat_store=chat_store,
            username=username,
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
                await restore_chat_history(chat_store, username, history)
                retry_prompt = _build_document_prompt(prompt, budgeted_documents, force_documents=True)
                retry_job_id, retry_result = await run_document_job(
                    gateway=gateway,
                    chat_store=chat_store,
                    username=username,
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
                    await restore_chat_history(chat_store, username, history)
                    return JSONResponse({"error": retry_result.get("error") or "Сервис временно недоступен"}, status_code=503)

            if response_requires_document_retry(response_text):
                logger.warning(
                    "Document safeguard fallback applied for user %s job %s after retry",
                    username,
                    job_id,
                )
                response_text = DOCUMENT_NO_INFORMATION_RESPONSE
                await restore_chat_history(chat_store, username, history)
                await chat_store.append_message(username, "user", history_entry)
                await chat_store.append_message(username, "assistant", response_text)

            response_text = normalize_document_response(response_text)
            return JSONResponse(
                {
                    "response": response_text or DOCUMENT_UNCLEAR_REQUEST_RESPONSE,
                    "files": [{"name": file_info["name"], "size": file_info["size"]} for file_info in staged_files],
                    "job_id": job_id,
                }
            )
        if status == "failed":
            await restore_chat_history(chat_store, username, history)
            return JSONResponse({"error": result.get("error") or "Сервис временно недоступен"}, status_code=503)
        if status == "cancelled":
            await restore_chat_history(chat_store, username, history)
            return JSONResponse({"error": "Генерация была отменена"}, status_code=409)
        await restore_chat_history(chat_store, username, history)
        return JSONResponse({"error": "Истекло время ожидания ответа модели"}, status_code=504)
    except HTTPException:
        log_file_parse_observability(
            username=username,
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
    await request.app.state.chat_store.clear_history(current_user["username"])
    return JSONResponse({"ok": True})


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









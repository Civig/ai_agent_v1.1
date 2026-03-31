import asyncio
import json
import logging
import os
import socket
import time
from contextlib import suppress
from typing import Any, Dict, Optional

import httpx

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover
    psutil = None

try:
    import pynvml
except ModuleNotFoundError:  # pragma: no cover
    pynvml = None

from config import settings
from llm_gateway import (
    AsyncChatStore,
    DEADLINE_EXCEEDED_ERROR,
    DEFAULT_CHAT_THREAD_ID,
    classify_observability_error,
    ERROR_TYPE_CANCELLED,
    ERROR_TYPE_INFERENCE_TIMEOUT,
    ERROR_TYPE_INTERNAL,
    ERROR_TYPE_MODEL_NOT_FOUND,
    ERROR_TYPE_NONE,
    ERROR_TYPE_PARSE,
    GENERIC_CHAT_ERROR,
    JOB_KIND_FILE_CHAT,
    JOB_KIND_PARSE,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    ParserChildEnqueueCancelled,
    TERMINAL_JOB_STATUSES,
    LIFECYCLE_STAGE_CHILD_ENQUEUED,
    LIFECYCLE_STAGE_PARSER_PREPARED,
    LLMGateway,
    WORKER_POOL_PARSER,
    compute_queue_wait_ms,
    current_time_ms,
    elapsed_ms,
    extract_job_observability_fields,
    prepare_ollama_messages_with_metrics,
)
from parser_stage import (
    delete_staged_raw_files,
    log_file_pipeline_observability,
    prepare_parser_job_artifacts,
    write_parser_result_metadata,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("llm_worker")
CANCELLED_TEXT = "Генерация остановлена"
DOCUMENT_NO_INFORMATION_RESPONSE = "В предоставленных документах нет информации для ответа на этот вопрос."
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


def resolve_job_thread_id(job: Dict[str, Any]) -> str:
    normalized = (job.get("thread_id") or "").strip()
    if normalized:
        return normalized

    file_chat = job.get("file_chat")
    if isinstance(file_chat, dict):
        file_chat_thread_id = (file_chat.get("thread_id") or "").strip()
        if file_chat_thread_id:
            return file_chat_thread_id

    return DEFAULT_CHAT_THREAD_ID


class NoLLMModelsAvailableError(RuntimeError):
    pass


class OllamaModelNotFoundError(RuntimeError):
    def __init__(self, model_name: str):
        self.model_name = model_name
        super().__init__(f"LLM model not found: {model_name}")


class JobCancelledByUser(RuntimeError):
    pass


class JobDeadlineExceeded(RuntimeError):
    pass


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


class OllamaWorkerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.tags_url = self.base_url.replace("/api/chat", "/api/tags")
        self.ps_url = self.base_url.replace("/api/chat", "/api/ps")
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        timeout = httpx.Timeout(
            connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
            read=settings.OLLAMA_READ_TIMEOUT_SECONDS,
            write=10.0,
            pool=5.0,
        )
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self.client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is None:
            raise RuntimeError("Ollama client is not initialized")

        last_exc: Optional[Exception] = None
        for attempt in range(1, settings.OLLAMA_RETRY_ATTEMPTS + 1):
            try:
                response = await self.client.request(method, url, **kwargs)
                if response.status_code >= 500 and attempt < settings.OLLAMA_RETRY_ATTEMPTS:
                    await response.aclose()
                    await asyncio.sleep(settings.OLLAMA_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                if attempt >= settings.OLLAMA_RETRY_ATTEMPTS:
                    break
                await asyncio.sleep(settings.OLLAMA_RETRY_BACKOFF_SECONDS * attempt)
        raise last_exc or RuntimeError("Ollama request failed")

    async def stream_chat(self, model_name: str, messages: list[dict[str, str]]) -> httpx.Response:
        if self.client is None:
            raise RuntimeError("Ollama client is not initialized")
        if not model_name:
            raise NoLLMModelsAvailableError("No LLM models available")

        last_exc: Optional[Exception] = None
        for attempt in range(1, settings.OLLAMA_RETRY_ATTEMPTS + 1):
            try:
                request = self.client.build_request(
                    "POST",
                    self.base_url,
                    json={"model": model_name, "messages": messages, "stream": True},
                    timeout=httpx.Timeout(
                        connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
                        read=settings.OLLAMA_READ_TIMEOUT_SECONDS,
                        write=10.0,
                        pool=5.0,
                    ),
                )
                response = await self.client.send(request, stream=True)
                if response.status_code == 404:
                    payload = None
                    try:
                        payload = json.loads((await response.aread()).decode("utf-8", errors="ignore") or "{}")
                    except Exception:
                        payload = None
                    finally:
                        await response.aclose()
                    error_message = (payload or {}).get("error", "")
                    if "not found" in error_message.lower():
                        raise OllamaModelNotFoundError(model_name)
                    raise httpx.HTTPStatusError(
                        f"Client error '404 Not Found' for url '{response.request.url}'",
                        request=response.request,
                        response=response,
                    )
                if response.status_code >= 500 and attempt < settings.OLLAMA_RETRY_ATTEMPTS:
                    await response.aclose()
                    await asyncio.sleep(settings.OLLAMA_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                if attempt >= settings.OLLAMA_RETRY_ATTEMPTS:
                    break
                await asyncio.sleep(settings.OLLAMA_RETRY_BACKOFF_SECONDS * attempt)
        raise last_exc or RuntimeError("Ollama stream request failed")

    async def fetch_model_catalog(self) -> dict[str, dict[str, str]]:
        response = await self.request_with_retry("GET", self.tags_url)
        payload = response.json()
        await response.aclose()
        catalog: dict[str, dict[str, str]] = {}
        for model_info in payload.get("models", []):
            model_name = model_info["name"]
            model_size = int(model_info.get("size") or 0)
            if model_size < 3 * 1024 * 1024 * 1024:
                model_type = "Легкая модель"
            elif model_size < 8 * 1024 * 1024 * 1024:
                model_type = "Средняя модель"
            else:
                model_type = "Тяжелая модель"
            catalog[model_name] = {
                "name": model_name,
                "description": f"{model_type} ({model_size // (1024 * 1024 * 1024)} GB)",
                "size": str(model_size),
                "status": "active",
            }
        if not catalog:
            raise NoLLMModelsAvailableError("No LLM models available")
        return catalog

    async def fetch_loaded_models(self) -> list[str]:
        try:
            response = await self.request_with_retry("GET", self.ps_url)
        except Exception:
            return []
        try:
            payload = response.json()
            return [model.get("name") for model in payload.get("models", []) if model.get("name")]
        finally:
            await response.aclose()


class LocalResourceMonitor:
    def __init__(self, ollama: Optional[OllamaWorkerClient]):
        self.ollama = ollama
        self.hostname = socket.gethostname()
        self.cpu_count = os.cpu_count() or 1

    def _memory_snapshot_mb(self) -> tuple[int, int]:
        if psutil is not None:
            vm = psutil.virtual_memory()
            return int(vm.total / (1024 * 1024)), int(vm.available / (1024 * 1024))
        if hasattr(os, "sysconf"):
            try:
                total_pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                total = int((total_pages * page_size) / (1024 * 1024))
                return total, max(total // 2, settings.SCHEDULER_RAM_SAFETY_MARGIN_MB + settings.SCHEDULER_TOKEN_GRANULARITY_MB)
            except (OSError, ValueError):
                pass
        return 0, 0

    def _cpu_percent(self) -> float:
        if psutil is not None:
            return float(psutil.cpu_percent(interval=None))
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()[0]
            return min(100.0, (load / max(self.cpu_count, 1)) * 100.0)
        return 0.0

    async def _query_gpu(self) -> Optional[dict[str, Any]]:
        selected_index = settings.WORKER_GPU_INDEX or 0
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                index = settings.WORKER_GPU_INDEX if settings.WORKER_GPU_INDEX is not None else 0
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                return {
                    "gpu_index": index,
                    "vram_total_mb": int(memory.total / (1024 * 1024)),
                    "vram_free_mb": int(memory.free / (1024 * 1024)),
                    "used_vram_mb": int(memory.used / (1024 * 1024)),
                    "gpu_utilization": float(utilization.gpu),
                }
            except Exception:
                logger.debug("pynvml is unavailable or failed, falling back to nvidia-smi", exc_info=True)
            finally:
                with suppress(Exception):
                    pynvml.nvmlShutdown()

        try:
            process = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=index,memory.total,memory.free,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        except (FileNotFoundError, TimeoutError, OSError):
            return None

        if process.returncode != 0:
            return None

        for line in stdout.decode("utf-8", errors="ignore").splitlines():
            parts = [item.strip() for item in line.split(",")]
            if len(parts) != 5:
                continue
            gpu_index = int(parts[0])
            if settings.WORKER_GPU_INDEX is not None and gpu_index != settings.WORKER_GPU_INDEX:
                continue
            return {
                "gpu_index": gpu_index,
                "vram_total_mb": int(parts[1]),
                "vram_free_mb": int(parts[2]),
                "used_vram_mb": int(parts[3]),
                "gpu_utilization": float(parts[4]),
            }
        return None

    async def collect_target_report(self) -> Dict[str, Any]:
        ram_total_mb, ram_free_mb = self._memory_snapshot_mb()
        cpu_percent = self._cpu_percent()
        loaded_models = await self.ollama.fetch_loaded_models() if self.ollama is not None else []
        gpu = await self._query_gpu() if settings.WORKER_TARGET_KIND in {"auto", "gpu"} else None

        if gpu is not None:
            usable_vram_mb = max(
                0,
                gpu["vram_free_mb"] - settings.SCHEDULER_GPU_SAFETY_MARGIN_MB - settings.SCHEDULER_GPU_FRAGMENTATION_MARGIN_MB,
            )
            base_capacity_tokens = max(1, usable_vram_mb // max(settings.SCHEDULER_TOKEN_GRANULARITY_MB, 1)) if gpu["vram_total_mb"] else 0
            return {
                "target_id": settings.WORKER_TARGET_ID,
                "node_id": settings.WORKER_NODE_ID,
                "target_kind": "gpu",
                "runtime_label": settings.WORKER_RUNTIME_LABEL,
                "supports_workloads": settings.worker_supported_workloads,
                "cpu_count": self.cpu_count,
                "cpu_percent": cpu_percent,
                "ram_total_mb": ram_total_mb,
                "ram_free_mb": ram_free_mb,
                "gpu_index": gpu["gpu_index"],
                "vram_total_mb": gpu["vram_total_mb"],
                "vram_free_mb": gpu["vram_free_mb"],
                "gpu_utilization": gpu["gpu_utilization"],
                "loaded_models": loaded_models,
                "base_capacity_tokens": base_capacity_tokens,
                "ollama_url": settings.OLLAMA_URL,
            }

        usable_ram_mb = max(0, ram_free_mb - settings.SCHEDULER_RAM_SAFETY_MARGIN_MB)
        ram_tokens = usable_ram_mb // max(settings.SCHEDULER_TOKEN_GRANULARITY_MB, 1) if usable_ram_mb else 0
        load_factor = max(0.25, (100.0 - cpu_percent) / 100.0)
        base_capacity_tokens = max(1, min(self.cpu_count, int(ram_tokens * load_factor) or 1))
        if ram_total_mb >= 12 * 1024:
            base_capacity_tokens = max(base_capacity_tokens, 8)
        return {
            "target_id": settings.WORKER_TARGET_ID,
            "node_id": settings.WORKER_NODE_ID,
            "target_kind": "cpu",
            "runtime_label": settings.WORKER_RUNTIME_LABEL,
            "supports_workloads": settings.worker_supported_workloads,
            "cpu_count": self.cpu_count,
            "cpu_percent": cpu_percent,
            "ram_total_mb": ram_total_mb,
            "ram_free_mb": ram_free_mb,
            "gpu_index": None,
            "vram_total_mb": 0,
            "vram_free_mb": 0,
            "gpu_utilization": 0.0,
            "loaded_models": loaded_models,
            "base_capacity_tokens": base_capacity_tokens,
            "ollama_url": settings.OLLAMA_URL,
        }


class LLMWorker:
    def __init__(self):
        self.gateway = LLMGateway(settings.REDIS_URL)
        self.chat_store = AsyncChatStore(settings.REDIS_URL, max_history=100)
        self.is_parser_pool = settings.WORKER_POOL == WORKER_POOL_PARSER
        self.ollama = None if self.is_parser_pool else OllamaWorkerClient(settings.OLLAMA_URL)
        self.monitor = LocalResourceMonitor(self.ollama)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{settings.WORKER_POOL}"
        self.target_kind = (os.getenv("WORKER_TARGET_KIND", "cpu").strip().lower() or "cpu")
        self.shutdown_event = asyncio.Event()
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self.active_tasks: dict[str, asyncio.Task[Any]] = {}

    async def start(self) -> None:
        await self.gateway.connect()
        await self.chat_store.connect()
        if self.ollama is not None:
            await self.ollama.connect()

        startup_tasks = {
            asyncio.create_task(self.heartbeat_loop()),
            asyncio.create_task(self.lease_loop()),
        }
        if not self.is_parser_pool:
            startup_tasks.add(asyncio.create_task(self.refresh_model_catalog_loop()))
        self.background_tasks.update(startup_tasks)
        try:
            await self.run()
        finally:
            self.shutdown_event.set()
            for task in list(self.background_tasks):
                task.cancel()
            for task in list(self.active_tasks.values()):
                task.cancel()
            for task in list(self.background_tasks):
                with suppress(asyncio.CancelledError):
                    await task
            for task in list(self.active_tasks.values()):
                with suppress(asyncio.CancelledError):
                    await task
            if self.ollama is not None:
                await self.ollama.close()
            await self.chat_store.close()
            await self.gateway.close()

    async def heartbeat_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                target_report = await self.monitor.collect_target_report()
                await self.gateway.report_target_heartbeat(target_report)
                await self.gateway.report_worker_heartbeat(
                    {
                        "worker_id": self.worker_id,
                        "worker_pool": settings.WORKER_POOL,
                        "target_id": settings.WORKER_TARGET_ID,
                        "target_kind": self.target_kind,
                        "node_id": settings.WORKER_NODE_ID,
                        "runtime_label": settings.WORKER_RUNTIME_LABEL,
                        "active_jobs": len(self.active_tasks),
                    }
                )
            except Exception:
                logger.exception("Worker heartbeat failed")
            await asyncio.sleep(max(1, settings.WORKER_HEARTBEAT_TTL_SECONDS // 3))

    async def refresh_model_catalog_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                catalog = await self.ollama.fetch_model_catalog()
                logger.info("Worker refreshed Ollama model catalog: %s", list(catalog.keys()))
                await self.gateway.set_model_catalog(catalog)
            except NoLLMModelsAvailableError as exc:
                logger.error("%s", exc)
            except Exception:
                logger.exception("Failed to refresh model catalog")
            await asyncio.sleep(settings.OLLAMA_MODEL_CATALOG_REFRESH_SECONDS)

    async def lease_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                for job_id in list(self.active_tasks.keys()):
                    await self.gateway.renew_job_lease(job_id)
            except Exception:
                logger.exception("Lease renewal failed")
            await asyncio.sleep(settings.WORKER_LEASE_RENEW_INTERVAL_SECONDS)

    async def run(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                job = await self.gateway.claim_dispatch_job(
                    worker_id=self.worker_id,
                    worker_pool=settings.WORKER_POOL,
                    target_id=settings.WORKER_TARGET_ID,
                    expected_target_kind=self.target_kind,
                )
                if not job:
                    await asyncio.sleep(settings.LLM_WORKER_IDLE_SLEEP_SECONDS)
                    continue
                task = asyncio.create_task(self.process_job(job))
                self.active_tasks[job["id"]] = task
                task.add_done_callback(lambda done, job_id=job["id"]: self._on_task_done(job_id, done))
            except Exception:
                logger.exception("Worker main loop failed")
                await asyncio.sleep(settings.LLM_WORKER_IDLE_SLEEP_SECONDS)

    def _on_task_done(self, job_id: str, task: asyncio.Task[Any]) -> None:
        self.active_tasks.pop(job_id, None)
        with suppress(Exception):
            task.result()

    async def _run_generation(
        self,
        *,
        job_id: str,
        model_name: str,
        history: list[dict[str, Any]],
        prompt: str,
        deadline_at: int,
        emit_tokens: bool,
    ) -> tuple[str, int]:
        assistant_text = ""
        inference_started = time.perf_counter()
        messages, governance_metrics = prepare_ollama_messages_with_metrics(history, prompt)
        logger.info(
            "Context governance job %s: final_prompt_chars=%s budget_applied=%s",
            job_id,
            governance_metrics["final_prompt_chars"],
            governance_metrics["budget_applied"],
        )
        async with asyncio.timeout(settings.LLM_JOB_TIMEOUT_SECONDS):
            response = await self.ollama.stream_chat(model_name, messages)
            try:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if deadline_at and int(time.time()) >= deadline_at:
                        raise JobDeadlineExceeded(DEADLINE_EXCEEDED_ERROR)
                    if await self.gateway.is_cancel_requested(job_id):
                        raise JobCancelledByUser(CANCELLED_TEXT)

                    payload = json.loads(line)
                    token = payload.get("message", {}).get("content") or payload.get("response")
                    if token:
                        assistant_text += token
                        if emit_tokens:
                            await self.gateway.emit_event(job_id, {"token": token})
                    if payload.get("done"):
                        break
            finally:
                await response.aclose()

        if not assistant_text.strip():
            return "Модель не вернула текст ответа.", elapsed_ms(inference_started)
        return assistant_text, elapsed_ms(inference_started)

    async def _run_file_chat_job(
        self,
        *,
        job: Dict[str, Any],
        history: list[dict[str, Any]],
        model_name: str,
        deadline_at: int,
    ) -> tuple[str, int]:
        file_chat = job.get("file_chat") or {}
        emit_tokens = not bool(file_chat.get("suppress_token_stream"))
        inference_ms = 0
        assistant_text, attempt_inference_ms = await self._run_generation(
            job_id=job["id"],
            model_name=model_name,
            history=history,
            prompt=job["prompt"],
            deadline_at=deadline_at,
            emit_tokens=emit_tokens,
        )
        inference_ms += attempt_inference_ms

        retry_prompt = (file_chat.get("retry_prompt") or "").strip()
        if retry_prompt and response_requires_document_retry(assistant_text):
            logger.warning("File chat retry triggered for job %s due to inaccessible-file phrasing", job["id"])
            assistant_text, retry_inference_ms = await self._run_generation(
                job_id=job["id"],
                model_name=model_name,
                history=history,
                prompt=retry_prompt,
                deadline_at=deadline_at,
                emit_tokens=False,
            )
            inference_ms += retry_inference_ms

        if response_requires_document_retry(assistant_text):
            logger.warning("File chat safeguard fallback applied for job %s after retry", job["id"])
            assistant_text = DOCUMENT_NO_INFORMATION_RESPONSE

        assistant_text = normalize_document_response(assistant_text)
        if file_chat.get("suppress_token_stream"):
            await self.gateway.emit_event(job["id"], {"result": assistant_text})
        return assistant_text, inference_ms

    async def _process_parser_job(self, job: Dict[str, Any]) -> None:
        job_id = job["id"]
        parse_started_at: Optional[float] = None
        if await self.gateway.is_cancel_requested(job_id):
            await self.gateway.mark_job_cancelled(job_id, worker_id=self.worker_id)
            return

        if not self.is_parser_pool:
            error_text = "Parser jobs must run on the parser worker pool"
            logger.warning("Parser job %s failed safely: %s", job_id, error_text)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)
            return
        if not settings.ENABLE_PARSER_STAGE:
            error_text = "Parser stage is disabled"
            logger.warning("Parser job %s failed safely: %s", job_id, error_text)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)
            return

        current_job = await self.gateway.get_job(job_id)
        current_job = current_job or job
        existing_child_job_id = await self.gateway.get_linked_child_job_id(job_id)
        staging_id = (current_job.get("staging_id") or job.get("staging_id") or "").strip()
        if not staging_id:
            error_text = "Parser job is missing staging_id"
            logger.warning("Parser job %s failed safely: %s", job_id, error_text)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)
            return

        if existing_child_job_id:
            raw_deleted = await asyncio.to_thread(
                delete_staged_raw_files,
                staging_id,
                staging_root=settings.PARSER_STAGING_ROOT,
            )
            await asyncio.to_thread(
                write_parser_result_metadata,
                staging_id,
                staging_root=settings.PARSER_STAGING_ROOT,
                payload={
                    "status": LIFECYCLE_STAGE_CHILD_ENQUEUED,
                    "child_job_id": existing_child_job_id,
                    "raw_deleted": raw_deleted,
                },
            )
            await self.gateway.mark_job_waiting_on_child(
                job_id,
                child_job_id=existing_child_job_id,
                lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
                parser_metadata_updates={
                    "phase": LIFECYCLE_STAGE_CHILD_ENQUEUED,
                    "raw_deleted": raw_deleted,
                    "child_job_id": existing_child_job_id,
                },
                worker_id=self.worker_id,
            )
            return

        try:
            parse_started_at = time.perf_counter()
            prepared = await asyncio.wait_for(
                asyncio.to_thread(
                    prepare_parser_job_artifacts,
                    staging_id=staging_id,
                    message=current_job.get("prompt") or "",
                    history=current_job.get("history") or [],
                    model_key=current_job.get("model_key") or "",
                    model_name=current_job.get("model_name") or "",
                    staging_root=settings.PARSER_STAGING_ROOT,
                ),
                timeout=settings.PARSER_JOB_TIMEOUT_SECONDS,
            )
            parser_record = await asyncio.to_thread(
                write_parser_result_metadata,
                staging_id,
                staging_root=settings.PARSER_STAGING_ROOT,
                payload={
                    "status": LIFECYCLE_STAGE_PARSER_PREPARED,
                    "raw_deleted": False,
                    **prepared,
                },
            )
            updated_job = dict(current_job)
            updated_job["parser_metadata"] = {
                **(current_job.get("parser_metadata") or {}),
                "phase": LIFECYCLE_STAGE_PARSER_PREPARED,
                "files": prepared["files"],
                "original_doc_chars": prepared["original_doc_chars"],
                "trimmed_doc_chars": prepared["trimmed_doc_chars"],
                "raw_deleted": False,
                "artifact": "meta/parser.json",
            }
            updated_job["lifecycle_stage"] = LIFECYCLE_STAGE_PARSER_PREPARED
            await self.gateway.save_job(updated_job)
            log_file_pipeline_observability(
                username=current_job.get("username") or job.get("username") or "unknown",
                job_kind=JOB_KIND_PARSE,
                file_count=len(prepared["files"]),
                receive_ms=0,
                parse_ms=elapsed_ms(parse_started_at),
                doc_chars=prepared["trimmed_doc_chars"],
                original_doc_chars=prepared["original_doc_chars"],
                trimmed_doc_chars=prepared["trimmed_doc_chars"],
                terminal_status="success",
                error_type=ERROR_TYPE_NONE,
                target_logger=logger,
            )
        except TimeoutError:
            error_text = "Parser artifact preparation timed out"
            log_file_pipeline_observability(
                username=current_job.get("username") or job.get("username") or "unknown",
                job_kind=JOB_KIND_PARSE,
                file_count=len((current_job.get("parser_metadata") or {}).get("files") or []),
                receive_ms=0,
                parse_ms=elapsed_ms(parse_started_at) if parse_started_at is not None else 0,
                doc_chars=0,
                original_doc_chars=0,
                trimmed_doc_chars=0,
                terminal_status="failed",
                error_type=classify_observability_error(error_text, phase="parse", default=ERROR_TYPE_PARSE),
                target_logger=logger,
            )
            logger.warning("Parser job %s failed: %s", job_id, error_text)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)
            return
        except Exception as exc:
            error_text = f"Parser artifact preparation failed: {str(exc) or 'unknown error'}"
            log_file_pipeline_observability(
                username=current_job.get("username") or job.get("username") or "unknown",
                job_kind=JOB_KIND_PARSE,
                file_count=len((current_job.get("parser_metadata") or {}).get("files") or []),
                receive_ms=0,
                parse_ms=elapsed_ms(parse_started_at) if parse_started_at is not None else 0,
                doc_chars=0,
                original_doc_chars=0,
                trimmed_doc_chars=0,
                terminal_status="failed",
                error_type=classify_observability_error(error_text, phase="parse", default=ERROR_TYPE_PARSE),
                target_logger=logger,
            )
            logger.warning("Parser job %s failed: %s", job_id, error_text, exc_info=True)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)
            return

        latest_job = await self.gateway.get_job(job_id)
        if latest_job and latest_job.get("status") in TERMINAL_JOB_STATUSES:
            return
        if await self.gateway.is_cancel_requested(job_id):
            await self.gateway.mark_job_cancelled(job_id, worker_id=self.worker_id)
            return

        try:
            child_job_id, child_created = await self.gateway.enqueue_child_job_once(
                job_id,
                prepared_llm_job={
                    **prepared["prepared_llm_job"],
                    "staging_id": staging_id,
                    "thread_id": resolve_job_thread_id(current_job or job),
                },
            )
            raw_deleted = await asyncio.to_thread(
                delete_staged_raw_files,
                staging_id,
                staging_root=settings.PARSER_STAGING_ROOT,
            )
            parser_record = await asyncio.to_thread(
                write_parser_result_metadata,
                staging_id,
                staging_root=settings.PARSER_STAGING_ROOT,
                payload={
                    "status": LIFECYCLE_STAGE_CHILD_ENQUEUED,
                    "child_job_id": child_job_id,
                    "raw_deleted": raw_deleted,
                },
            )
            logger.info(
                "Parser job %s prepared staged documents: file_count=%s child_job_id=%s raw_deleted=%s",
                job_id,
                len(prepared["files"]),
                child_job_id,
                parser_record.get("raw_deleted"),
            )
            await self.gateway.mark_job_waiting_on_child(
                job_id,
                child_job_id=child_job_id,
                lifecycle_stage=LIFECYCLE_STAGE_CHILD_ENQUEUED,
                parser_metadata_updates={
                    "phase": LIFECYCLE_STAGE_CHILD_ENQUEUED,
                    "files": prepared["files"],
                    "original_doc_chars": prepared["original_doc_chars"],
                    "trimmed_doc_chars": prepared["trimmed_doc_chars"],
                    "raw_deleted": raw_deleted,
                    "artifact": "meta/parser.json",
                    "child_job_id": child_job_id,
                    "child_job_created": child_created,
                },
                worker_id=self.worker_id,
            )
        except ParserChildEnqueueCancelled:
            latest_job = await self.gateway.get_job(job_id)
            if latest_job and latest_job.get("status") in TERMINAL_JOB_STATUSES:
                return
            await self.gateway.mark_job_cancelled(job_id, worker_id=self.worker_id)
            return
        except Exception as exc:
            error_text = f"Parser child enqueue failed: {str(exc) or 'unknown error'}"
            logger.warning("Parser job %s failed: %s", job_id, error_text, exc_info=True)
            await self.gateway.mark_job_failed(job_id, error_text, worker_id=self.worker_id)

    async def process_job(self, job: Dict[str, Any]) -> None:
        if job.get("job_kind") == JOB_KIND_PARSE:
            await self._process_parser_job(job)
            return

        job_id = job["id"]
        username = job["username"]
        thread_id = resolve_job_thread_id(job)
        model_name = job["model_name"]
        deadline_at = int(job.get("deadline_at") or 0)
        assistant_text = ""
        inference_ms = 0
        terminal_status = JOB_STATUS_FAILED
        error_type = ERROR_TYPE_INTERNAL
        started_at = time.perf_counter()
        job_fields = extract_job_observability_fields(job)
        queue_wait_ms = int(job.get("queue_wait_ms") or compute_queue_wait_ms(job))
        created_at_ms = int(job.get("created_at_ms") or job.get("enqueued_at_ms") or current_time_ms())
        try:
            logger.info(
                "Processing LLM job %s for user %s with model %s prompt_size=%s history_messages=%s",
                job_id,
                username,
                model_name,
                len(job.get("prompt") or ""),
                len(job.get("history") or []),
            )
            if await self.gateway.is_cancel_requested(job_id):
                await self.chat_store.append_message(username, "assistant", CANCELLED_TEXT, thread_id=thread_id)
                await self.gateway.mark_job_cancelled(job_id, worker_id=self.worker_id)
                return

            history = job.get("history") or []
            if job.get("job_kind") == JOB_KIND_FILE_CHAT and isinstance(job.get("file_chat"), dict):
                assistant_text, inference_ms = await self._run_file_chat_job(
                    job=job,
                    history=history,
                    model_name=model_name,
                    deadline_at=deadline_at,
                )
            else:
                assistant_text, inference_ms = await self._run_generation(
                    job_id=job_id,
                    model_name=model_name,
                    history=history,
                    prompt=job["prompt"],
                    deadline_at=deadline_at,
                    emit_tokens=True,
                )
            await self.chat_store.append_message(username, "assistant", assistant_text, thread_id=thread_id)
            await self.gateway.mark_job_completed(job_id, assistant_text, worker_id=self.worker_id)
            terminal_status = JOB_STATUS_COMPLETED
            error_type = ERROR_TYPE_NONE
            logger.info("Completed LLM job %s in %.2fs", job_id, time.perf_counter() - started_at)
        except JobCancelledByUser:
            await self.chat_store.append_message(username, "assistant", CANCELLED_TEXT, thread_id=thread_id)
            await self.gateway.mark_job_cancelled(job_id, worker_id=self.worker_id)
            terminal_status = JOB_STATUS_CANCELLED
            error_type = classify_observability_error(
                CANCELLED_TEXT,
                terminal_status=JOB_STATUS_CANCELLED,
                default=ERROR_TYPE_CANCELLED,
            )
        except JobDeadlineExceeded:
            await self.gateway.mark_job_failed(job_id, DEADLINE_EXCEEDED_ERROR, worker_id=self.worker_id)
            terminal_status = JOB_STATUS_FAILED
            error_type = classify_observability_error(
                DEADLINE_EXCEEDED_ERROR,
                phase="inference",
                default=ERROR_TYPE_INFERENCE_TIMEOUT,
            )
        except OllamaModelNotFoundError as exc:
            logger.error("LLM job %s failed: %s", job_id, exc)
            await self.chat_store.append_message(username, "assistant", str(exc), thread_id=thread_id)
            await self.gateway.mark_job_failed(job_id, str(exc), worker_id=self.worker_id)
            terminal_status = JOB_STATUS_FAILED
            error_type = classify_observability_error(
                str(exc),
                default=ERROR_TYPE_MODEL_NOT_FOUND,
            )
        except NoLLMModelsAvailableError as exc:
            logger.error("LLM job %s failed: %s", job_id, exc)
            await self.chat_store.append_message(username, "assistant", str(exc), thread_id=thread_id)
            await self.gateway.mark_job_failed(job_id, str(exc), worker_id=self.worker_id)
            terminal_status = JOB_STATUS_FAILED
            error_type = classify_observability_error(
                str(exc),
                default=ERROR_TYPE_INTERNAL,
            )
        except TimeoutError:
            logger.warning("LLM job %s timed out", job_id)
            await self.chat_store.append_message(username, "assistant", GENERIC_CHAT_ERROR, thread_id=thread_id)
            await self.gateway.mark_job_failed(job_id, GENERIC_CHAT_ERROR, worker_id=self.worker_id)
            terminal_status = JOB_STATUS_FAILED
            error_type = classify_observability_error(
                "timeout",
                phase="inference",
                default=ERROR_TYPE_INFERENCE_TIMEOUT,
            )
        except Exception:
            logger.exception("LLM job %s failed", job_id)
            await self.chat_store.append_message(username, "assistant", GENERIC_CHAT_ERROR, thread_id=thread_id)
            await self.gateway.mark_job_failed(job_id, GENERIC_CHAT_ERROR, worker_id=self.worker_id)
            terminal_status = JOB_STATUS_FAILED
            error_type = classify_observability_error(
                GENERIC_CHAT_ERROR,
                default=ERROR_TYPE_INTERNAL,
            )
        finally:
            total_job_ms = max(0, current_time_ms() - created_at_ms)
            logger.info(
                "job_terminal_observability job_id=%s username=%s job_kind=%s workload_class=%s target_kind=%s "
                "model_key=%s model_name=%s file_count=%s doc_chars=%s prompt_chars=%s history_messages=%s queue_wait_ms=%s "
                "inference_ms=%s total_ms=%s total_job_ms=%s terminal_status=%s error_type=%s",
                job_fields["job_id"],
                job_fields["username"],
                job_fields["job_kind"],
                job_fields["workload_class"],
                job_fields["target_kind"],
                job_fields["model_key"],
                job_fields["model_name"],
                job_fields["file_count"],
                job_fields["doc_chars"],
                job_fields["prompt_chars"],
                job_fields["history_messages"],
                queue_wait_ms,
                inference_ms,
                total_job_ms,
                total_job_ms,
                terminal_status,
                error_type,
            )
            logger.info("LLM job %s finished in %.2fs", job_id, time.perf_counter() - started_at)


async def main() -> None:
    worker = LLMWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())










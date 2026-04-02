import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import requests
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
INSECURE_SECRET_KEYS = {
    "change-this-secret-key",
    "change-me-to-a-long-random-secret",
}
MIN_SECRET_KEY_LENGTH = 32


def parse_group_mapping(value: Optional[str]) -> tuple[str, ...]:
    normalized_groups: list[str] = []
    seen: set[str] = set()
    for raw_group in (value or "").split(","):
        candidate = raw_group.strip()
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_groups.append(key)
    return tuple(normalized_groups)


def _load_environment_file() -> None:
    env_path = Path('.env')
    if not env_path.exists():
        return

    for encoding in ('utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'cp1251'):
        try:
            load_dotenv(env_path, override=False, encoding=encoding)
            logger.info("Loaded .env using %s", encoding)
            return
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.warning("Failed to load .env with %s: %s", encoding, exc)
            return

    logger.warning("Failed to load .env because no supported encoding matched")


_load_environment_file()


class Settings(BaseSettings):
    LDAP_SERVER: str = "ldap://your-dc-server.local"
    LDAP_DOMAIN: str = "your-domain.local"
    LDAP_BASE_DN: str = "dc=your-domain,dc=local"
    LDAP_NETBIOS_DOMAIN: str = "DOMAIN"

    KERBEROS_REALM: str = "YOUR-DOMAIN.LOCAL"
    KERBEROS_KDC: str = "your-dc-server.local"

    SECRET_KEY: str = "change-this-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None
    TRUSTED_AUTH_PROXY_ENABLED: bool = False
    SSO_ENABLED: bool = False
    SSO_LOGIN_PATH: str = "/auth/sso/login"
    SSO_SERVICE_PRINCIPAL: str = ""
    SSO_KEYTAB_PATH: str = "/etc/corporate-ai-sso/http.keytab"
    MODEL_POLICY_DIR: str = "model_policies"
    MODEL_ACCESS_CODING_GROUPS: str = ""
    MODEL_ACCESS_ADMIN_GROUPS: str = ""

    OLLAMA_URL: str = "http://127.0.0.1:11434/api/chat"
    DEFAULT_MODEL: Optional[str] = None
    AUTO_START_OLLAMA: bool = False
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 10.0
    OLLAMA_READ_TIMEOUT_SECONDS: float = 300.0
    OLLAMA_RETRY_ATTEMPTS: int = 3
    OLLAMA_RETRY_BACKOFF_SECONDS: float = 0.5
    OLLAMA_MODEL_CATALOG_REFRESH_SECONDS: int = 30

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 15.0
    REDIS_CONNECT_TIMEOUT_SECONDS: float = 5.0
    REDIS_HEALTHCHECK_INTERVAL_SECONDS: int = 15
    REDIS_RETRY_ON_TIMEOUT: bool = True
    REDIS_CONNECT_RETRY_ATTEMPTS: int = 5
    REDIS_CONNECT_RETRY_BACKOFF_SECONDS: float = 0.5
    REDIS_SENTINELS: str = ""
    REDIS_SENTINEL_MASTER: str = "mymaster"
    PERSISTENT_DB_ENABLED: bool = False
    PERSISTENT_DB_URL: str = ""
    PERSISTENT_DB_ECHO: bool = False
    PERSISTENT_DB_POOL_PRE_PING: bool = True
    PERSISTENT_DB_BOOTSTRAP_SCHEMA: bool = False
    PERSISTENT_DB_SHADOW_COMPARE: bool = False
    RATE_LIMIT_REQUESTS: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_RATE_LIMIT_REQUESTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    LLM_DEFAULT_CONTEXT_TOKENS: int = 4096
    LLM_DEFAULT_MAX_OUTPUT_TOKENS: int = 1024
    LLM_JOB_TIMEOUT_SECONDS: int = 300
    LLM_JOB_DEADLINE_SECONDS: int = 420
    LLM_JOB_TTL_SECONDS: int = 1800
    LLM_EVENT_STREAM_TTL_SECONDS: int = 1800
    LLM_WORKER_IDLE_SLEEP_SECONDS: float = 0.2
    LLM_GPU_WEIGHT_MULTIPLIER: float = 1.10
    LLM_CPU_WEIGHT_MULTIPLIER: float = 1.35
    LLM_GPU_RUNTIME_OVERHEAD_MB: int = 768
    LLM_CPU_RUNTIME_OVERHEAD_MB: int = 512
    LLM_KV_CACHE_MB_PER_1K_TOKENS: int = 96
    LLM_PINNED_MODELS: str = ""
    ENABLE_PARSER_STAGE: bool = False
    ENABLE_PARSER_PUBLIC_CUTOVER: bool = False
    PARSER_STAGING_ROOT: str = "/tmp/corporate-ai-parser-staging"
    PARSER_JOB_TIMEOUT_SECONDS: int = 300
    PARSER_STAGING_TTL_SECONDS: int = 3600
    FILE_PROCESSING_MAX_FILES: int = 10
    FILE_PROCESSING_MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024
    FILE_PROCESSING_MAX_TOTAL_SIZE_BYTES: int = 500 * 1024 * 1024
    FILE_PROCESSING_MAX_DOCUMENT_CHARS: int = 12_000
    FILE_PROCESSING_MAX_PDF_PAGES: int = 20
    FILE_PROCESSING_IMAGE_MAX_DIMENSION: int = 2000
    FILE_PROCESSING_OCR_TIMEOUT_SECONDS: float = 30.0

    SCHEDULER_LOOP_INTERVAL_SECONDS: float = 0.5
    SCHEDULER_REAPER_INTERVAL_SECONDS: float = 5.0
    SCHEDULER_JOB_LEASE_SECONDS: int = 30
    SCHEDULER_HEARTBEAT_TTL_SECONDS: int = 15
    TARGET_HEARTBEAT_TTL_SECONDS: int = 15
    WORKER_HEARTBEAT_TTL_SECONDS: int = 15
    WORKER_CLAIM_BLOCK_TIMEOUT_SECONDS: int = 1
    WORKER_LEASE_RENEW_INTERVAL_SECONDS: int = 5
    SCHEDULER_QUEUE_SCAN_DEPTH: int = 8
    SCHEDULER_MAX_JOB_RETRIES: int = 2
    SCHEDULER_QUEUE_FACTOR: int = 4
    SCHEDULER_MIN_QUEUE_DEPTH: int = 64
    SCHEDULER_BACKPRESSURE_WORKER_WEIGHT: int = 2
    SCHEDULER_TOKEN_GRANULARITY_MB: int = 512
    SCHEDULER_GPU_SAFETY_MARGIN_MB: int = 2048
    SCHEDULER_GPU_FRAGMENTATION_MARGIN_MB: int = 1024
    SCHEDULER_RAM_SAFETY_MARGIN_MB: int = 4096
    SCHEDULER_CPU_LOAD_SHED_THRESHOLD: float = 90.0
    SCHEDULER_CHAT_RESERVED_RATIO: float = 0.50
    SCHEDULER_SIEM_RESERVED_RATIO: float = 0.25

    WORKER_POOL: str = "chat"
    WORKER_TARGET_ID: str = "ollama-main"
    WORKER_NODE_ID: str = "local-node"
    WORKER_TARGET_KIND: str = "auto"
    WORKER_GPU_INDEX: Optional[int] = None
    WORKER_SUPPORTED_WORKLOADS: str = ""
    WORKER_RUNTIME_LABEL: str = "ollama"

    DEBUG_LOAD_MAX_TASKS: int = 20
    DEBUG_LOAD_TIMEOUT_SECONDS: int = 120
    DEBUG_LOAD_ENABLED: bool = False

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_RELOAD: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = None
        case_sensitive = False
        extra = "allow"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        secret = value.strip()
        if secret in INSECURE_SECRET_KEYS:
            raise ValueError("SECRET_KEY uses an insecure default value and must be overridden")
        if len(secret) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters long")
        return secret

    @field_validator("WORKER_POOL")
    @classmethod
    def validate_worker_pool(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"chat", "siem", "batch", "parser"}:
            raise ValueError("WORKER_POOL must be one of: chat, siem, batch, parser")
        return normalized

    @field_validator("WORKER_TARGET_KIND")
    @classmethod
    def validate_target_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cpu", "gpu"}:
            raise ValueError("WORKER_TARGET_KIND must be one of: auto, cpu, gpu")
        return normalized

    @property
    def ollama_tags_url(self) -> str:
        return self.OLLAMA_URL.replace("/api/chat", "/api/tags")

    @property
    def ollama_generate_url(self) -> str:
        return self.OLLAMA_URL.replace("/api/chat", "/api/generate")

    @property
    def worker_supported_workloads(self) -> list[str]:
        items = [item.strip().lower() for item in self.WORKER_SUPPORTED_WORKLOADS.split(",") if item.strip()]
        if items:
            return items
        if self.WORKER_POOL == "parser":
            return ["parse"]
        return [self.WORKER_POOL]

    @property
    def redis_connection_kwargs(self) -> Dict[str, object]:
        return {
            "socket_timeout": self.REDIS_SOCKET_TIMEOUT_SECONDS,
            "socket_connect_timeout": self.REDIS_CONNECT_TIMEOUT_SECONDS,
            "health_check_interval": self.REDIS_HEALTHCHECK_INTERVAL_SECONDS,
            "retry_on_timeout": self.REDIS_RETRY_ON_TIMEOUT,
        }

    @property
    def redis_sentinels(self) -> list[tuple[str, int]]:
        sentinels: list[tuple[str, int]] = []
        for item in self.REDIS_SENTINELS.split(","):
            raw = item.strip()
            if not raw:
                continue
            host, _, port = raw.partition(":")
            sentinels.append((host.strip(), int(port or 26379)))
        return sentinels

    @property
    def persistent_db_url_configured(self) -> bool:
        return bool(self.PERSISTENT_DB_URL.strip())

    @property
    def pinned_models(self) -> list[str]:
        return [item.strip() for item in self.LLM_PINNED_MODELS.split(",") if item.strip()]

    @property
    def model_policy_dir(self) -> Path:
        raw_path = (self.MODEL_POLICY_DIR or "model_policies").strip()
        candidate = Path(raw_path)
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parent / candidate

    @property
    def model_access_coding_groups(self) -> tuple[str, ...]:
        return parse_group_mapping(self.MODEL_ACCESS_CODING_GROUPS)

    @property
    def model_access_admin_groups(self) -> tuple[str, ...]:
        return parse_group_mapping(self.MODEL_ACCESS_ADMIN_GROUPS)

    def _build_model_catalog(self, payload: Dict[str, object]) -> Dict[str, Dict[str, str]]:
        available_models: Dict[str, Dict[str, str]] = {}
        for model_info in payload.get("models", []):
            model_name = model_info["name"]
            model_size = int(model_info.get("size") or 0)

            if model_size < 3 * 1024 * 1024 * 1024:
                model_type = "Легкая модель"
            elif model_size < 8 * 1024 * 1024 * 1024:
                model_type = "Средняя модель"
            else:
                model_type = "Тяжелая модель"

            available_models[model_name] = {
                "name": model_name,
                "description": f"{model_type} ({model_size // (1024 * 1024 * 1024)} GB)",
                "size": str(model_size),
                "status": "active",
            }
        return available_models

    def get_available_models(self) -> Dict[str, Dict[str, str]]:
        try:
            response = requests.get(self.ollama_tags_url, timeout=5)
            response.raise_for_status()
            available_models = self._build_model_catalog(response.json())
            if available_models:
                logger.info("Available Ollama models: %s", list(available_models.keys()))
                return available_models
            logger.error("No LLM models available from Ollama at %s", self.ollama_tags_url)
        except Exception as exc:
            logger.warning("Failed to fetch models from Ollama: %s", exc)
        return {}

    def pick_available_model(self, available_models: Dict[str, Dict[str, str]]) -> Optional[str]:
        if not available_models:
            return None
        if self.DEFAULT_MODEL and self.DEFAULT_MODEL in available_models:
            return self.DEFAULT_MODEL
        if self.DEFAULT_MODEL:
            for key, model_info in available_models.items():
                if model_info.get("name") == self.DEFAULT_MODEL:
                    return key
        fallback_key = next(iter(available_models))
        if self.DEFAULT_MODEL and fallback_key != self.DEFAULT_MODEL:
            logger.warning("Default model %s is unavailable; falling back to %s", self.DEFAULT_MODEL, fallback_key)
        return fallback_key


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

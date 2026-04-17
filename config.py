import ipaddress
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
INSECURE_SECRET_KEYS = {
    "change-this-secret-key",
    "change-me-to-a-long-random-secret",
}
INSECURE_PASSWORD_PLACEHOLDERS = {
    "change-me",
    "changeme",
    "default",
    "password",
    "secret",
    "test",
    "demo",
    "redis",
    "postgres",
}
LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}
MIN_SECRET_KEY_LENGTH = 32
LOCAL_ADMIN_USERNAME_ALLOWED_RE = r"^[A-Za-z0-9._-]+$"
LAB_USER_CANONICAL_PRINCIPAL_RE = r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$"
INSTALL_PROFILE_ENTERPRISE = "enterprise"
INSTALL_PROFILE_STANDALONE_GPU_LAB = "standalone_gpu_lab"
AUTH_MODE_AD = "ad"
AUTH_MODE_LAB_OPEN = "lab_open"


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


def validate_cidr_list(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        ipaddress.ip_network(candidate, strict=False)
    return raw


def secret_looks_like_placeholder(value: Optional[str]) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return True
    if normalized in INSECURE_PASSWORD_PLACEHOLDERS:
        return True
    return normalized.startswith("change-me") or normalized.startswith("changeme")


def url_hostname(url: Optional[str]) -> str:
    parsed = urlparse((url or "").strip())
    return (parsed.hostname or "").strip().lower()


def url_password(url: Optional[str]) -> str:
    parsed = urlparse((url or "").strip())
    return (parsed.password or "").strip()


def is_non_local_service(url: Optional[str]) -> bool:
    hostname = url_hostname(url)
    return bool(hostname) and hostname not in LOCALHOST_NAMES


def normalize_simple_username(value: str, *, default: str, field_name: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        return default
    if not Path(candidate).name == candidate:
        raise ValueError(f"{field_name} must be a simple username without path separators")
    if not re.fullmatch(LOCAL_ADMIN_USERNAME_ALLOWED_RE, candidate):
        raise ValueError(f"{field_name} contains unsupported characters")
    return candidate


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
    INSTALL_PROFILE: str = INSTALL_PROFILE_ENTERPRISE
    AUTH_MODE: str = AUTH_MODE_AD
    LAB_OPEN_AUTH_ACK: bool = False
    LAB_USER_USERNAME: str = "lab_user"
    LAB_USER_CANONICAL_PRINCIPAL: str = "lab_user@LOCAL.LAB"

    LDAP_SERVER: str = "ldap://your-dc-server.local"
    LDAP_GSSAPI_SERVICE_HOST: str = ""
    LDAP_DOMAIN: str = "your-domain.local"
    LDAP_BASE_DN: str = "dc=your-domain,dc=local"
    LDAP_NETBIOS_DOMAIN: str = "DOMAIN"
    INSTALL_TEST_USER: str = ""

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
    TRUSTED_PROXY_SOURCE_CIDRS: str = "127.0.0.1/32,::1/128"
    SSO_ENABLED: bool = False
    SSO_LOGIN_PATH: str = "/auth/sso/login"
    SSO_SERVICE_PRINCIPAL: str = ""
    SSO_KEYTAB_PATH: str = "/etc/corporate-ai-sso/http.keytab"
    LOCAL_ADMIN_ENABLED: bool = False
    LOCAL_ADMIN_USERNAME: str = "admin_ai"
    LOCAL_ADMIN_PASSWORD_HASH: str = ""
    LOCAL_ADMIN_FORCE_ROTATE: bool = False
    LOCAL_ADMIN_BOOTSTRAP_REQUIRED: bool = False
    STANDALONE_CHAT_AUTH_ENABLED: bool = False
    STANDALONE_CHAT_USERNAME: str = "demo_ai"
    STANDALONE_CHAT_PASSWORD_HASH: str = ""
    STANDALONE_CHAT_FORCE_ROTATE: bool = False
    STANDALONE_CHAT_BOOTSTRAP_REQUIRED: bool = False
    MODEL_POLICY_DIR: str = "model_policies"
    MODEL_REGISTRY_PATH: str = "models/catalog.json"
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
    POSTGRES_PASSWORD: str = ""
    PERSISTENT_DB_ECHO: bool = False
    PERSISTENT_DB_POOL_PRE_PING: bool = True
    PERSISTENT_DB_BOOTSTRAP_SCHEMA: bool = False
    PERSISTENT_DB_SHADOW_COMPARE: bool = False
    PERSISTENT_DB_READ_THREADS: bool = False
    PERSISTENT_DB_READ_MESSAGES: bool = False
    PERSISTENT_DB_DUAL_WRITE_CONVERSATION: bool = False
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
    ADMIN_DASHBOARD_TELEMETRY_INTERVAL_SECONDS: int = 5
    ADMIN_DASHBOARD_HISTORY_RETENTION_SECONDS: int = 24 * 60 * 60
    ADMIN_DASHBOARD_EVENT_LOG_MAX_ITEMS: int = 200
    ADMIN_DASHBOARD_QUEUE_DEPTH_WARN_THRESHOLD: int = 10
    ADMIN_DASHBOARD_CHAT_BACKLOG_WARN_THRESHOLD: int = 5
    ADMIN_DASHBOARD_PARSER_BACKLOG_WARN_THRESHOLD: int = 5
    ADMIN_DASHBOARD_USERS: str = ""

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

    @field_validator("REDIS_PASSWORD", "POSTGRES_PASSWORD")
    @classmethod
    def validate_placeholder_passwords(cls, value: str) -> str:
        secret = value.strip()
        if secret and secret_looks_like_placeholder(secret):
            raise ValueError("Password uses an insecure placeholder value and must be overridden")
        return secret

    @field_validator("INSTALL_PROFILE")
    @classmethod
    def validate_install_profile(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {INSTALL_PROFILE_ENTERPRISE, INSTALL_PROFILE_STANDALONE_GPU_LAB}:
            raise ValueError("INSTALL_PROFILE must be one of: enterprise, standalone_gpu_lab")
        return normalized

    @field_validator("AUTH_MODE")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {AUTH_MODE_AD, AUTH_MODE_LAB_OPEN}:
            raise ValueError("AUTH_MODE must be one of: ad, lab_open")
        return normalized

    @field_validator("LOCAL_ADMIN_USERNAME")
    @classmethod
    def validate_local_admin_username(cls, value: str) -> str:
        return normalize_simple_username(value, default="admin_ai", field_name="LOCAL_ADMIN_USERNAME")

    @field_validator("STANDALONE_CHAT_USERNAME")
    @classmethod
    def validate_standalone_chat_username(cls, value: str) -> str:
        return normalize_simple_username(value, default="demo_ai", field_name="STANDALONE_CHAT_USERNAME")

    @field_validator("LAB_USER_USERNAME")
    @classmethod
    def validate_lab_user_username(cls, value: str) -> str:
        return normalize_simple_username(value, default="lab_user", field_name="LAB_USER_USERNAME")

    @field_validator("LAB_USER_CANONICAL_PRINCIPAL")
    @classmethod
    def validate_lab_user_canonical_principal(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            return "lab_user@LOCAL.LAB"
        if not re.fullmatch(LAB_USER_CANONICAL_PRINCIPAL_RE, candidate):
            raise ValueError("LAB_USER_CANONICAL_PRINCIPAL must look like username@REALM")
        return candidate

    @field_validator("TRUSTED_PROXY_SOURCE_CIDRS")
    @classmethod
    def validate_trusted_proxy_source_cidrs(cls, value: str) -> str:
        try:
            return validate_cidr_list(value)
        except ValueError as exc:
            raise ValueError("TRUSTED_PROXY_SOURCE_CIDRS must contain a comma-separated list of valid CIDRs") from exc

    @model_validator(mode="after")
    def validate_service_secret_requirements(self) -> "Settings":
        redis_url_secret = url_password(self.REDIS_URL)
        if redis_url_secret and secret_looks_like_placeholder(redis_url_secret):
            raise ValueError("REDIS_URL embeds an insecure placeholder password")
        if is_non_local_service(self.REDIS_URL) and not self.REDIS_PASSWORD.strip():
            raise ValueError("REDIS_PASSWORD must be set for non-local Redis deployments")

        db_url_secret = url_password(self.PERSISTENT_DB_URL)
        if db_url_secret and secret_looks_like_placeholder(db_url_secret):
            raise ValueError("PERSISTENT_DB_URL embeds an insecure placeholder password")
        if self.PERSISTENT_DB_ENABLED and is_non_local_service(self.PERSISTENT_DB_URL) and not self.POSTGRES_PASSWORD.strip():
            raise ValueError("POSTGRES_PASSWORD must be set for non-local PostgreSQL deployments")
        if self.SSO_ENABLED and self.TRUSTED_AUTH_PROXY_ENABLED and not self.TRUSTED_PROXY_SOURCE_CIDRS.strip():
            raise ValueError("TRUSTED_PROXY_SOURCE_CIDRS must be set when trusted proxy SSO is enabled")
        return self

    @model_validator(mode="after")
    def validate_auth_profile_contract(self) -> "Settings":
        if self.INSTALL_PROFILE == INSTALL_PROFILE_ENTERPRISE and self.AUTH_MODE != AUTH_MODE_AD:
            raise ValueError("INSTALL_PROFILE=enterprise requires AUTH_MODE=ad")
        if self.AUTH_MODE == AUTH_MODE_LAB_OPEN and not self.LAB_OPEN_AUTH_ACK:
            raise ValueError("AUTH_MODE=lab_open requires LAB_OPEN_AUTH_ACK=true")
        if self.STANDALONE_CHAT_AUTH_ENABLED and not self.STANDALONE_CHAT_PASSWORD_HASH.strip():
            raise ValueError("STANDALONE_CHAT_PASSWORD_HASH must be set when standalone chat auth is enabled")

        canonical_local_part = self.LAB_USER_CANONICAL_PRINCIPAL.split("@", 1)[0]
        normalized_local_part = normalize_simple_username(
            canonical_local_part,
            default=self.LAB_USER_USERNAME,
            field_name="LAB_USER_CANONICAL_PRINCIPAL",
        )
        if normalized_local_part != self.LAB_USER_USERNAME:
            raise ValueError("LAB_USER_CANONICAL_PRINCIPAL must match LAB_USER_USERNAME")
        return self

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
    def model_registry_path(self) -> Path:
        raw_path = (self.MODEL_REGISTRY_PATH or "models/catalog.json").strip()
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

    @property
    def lab_open_auth_enabled(self) -> bool:
        return self.AUTH_MODE == AUTH_MODE_LAB_OPEN and bool(self.LAB_OPEN_AUTH_ACK)

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

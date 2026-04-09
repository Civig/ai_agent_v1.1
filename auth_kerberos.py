import json
import logging
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from ldap3.utils.conv import escape_filter_chars

from config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TOKEN_REVOKE_PREFIX = "auth:revoked"
AUTH_SOURCE_PASSWORD = "password"
AUTH_SOURCE_SSO = "sso"
IDENTITY_VERSION = 1
MODEL_POLICY_FILENAME = "policy.json"
MODEL_POLICY_CATEGORY_ORDER = {"general": 0, "coding": 1, "admin": 2}
MODEL_POLICY_GENERAL_CATEGORY = "general"
MODEL_POLICY_CATEGORY_GROUP_MAPPING = {
    "coding": "model_access_coding_groups",
    "admin": "model_access_admin_groups",
}


class KerberosAuth:
    def __init__(self):
        self.realm = settings.KERBEROS_REALM
        self.kdc = settings.KERBEROS_KDC
        self.ldap_server = settings.LDAP_SERVER
        self.ldap_gssapi_service_host = settings.LDAP_GSSAPI_SERVICE_HOST.strip()
        self.base_dn = settings.LDAP_BASE_DN
        self.ldap_domain = settings.LDAP_DOMAIN

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        normalized = normalize_username(username)
        if not normalized or not password:
            logger.warning("Rejected invalid authentication input")
            return None

        ticket_cache = self._create_ticket_cache(normalized)
        krb5_config = self._create_krb5_config()
        try:
            logger.info("Authenticating user via Kerberos: %s", normalized)
            if not self.get_ticket(normalized, password, ticket_cache, krb5_config):
                return None

            user_info = self.get_user_info_from_ldap(normalized, ticket_cache, krb5_config)
            if user_info:
                logger.info("User %s authenticated successfully", normalized)
                return user_info
            return None
        except Exception:
            logger.exception("Authentication error for %s", normalized)
            return None
        finally:
            self.destroy_ticket(ticket_cache, krb5_config)

    def _create_ticket_cache(self, username: str) -> str:
        fd, path = tempfile.mkstemp(prefix=f"krb5cc_{username}_")
        os.close(fd)
        return path

    def _create_krb5_config(self) -> str:
        domain = self.ldap_domain.lower()
        realm = self.realm.upper()
        hostname_canonicalization = ""
        if self.ldap_gssapi_service_host:
            hostname_canonicalization = (
                "    dns_canonicalize_hostname = false\n"
                '    qualify_shortname = ""\n'
            )
        config = (
            "[libdefaults]\n"
            f"    default_realm = {realm}\n"
            "    dns_lookup_kdc = false\n"
            "    dns_lookup_realm = false\n"
            f"{hostname_canonicalization}"
            "    rdns = false\n\n"
            "[realms]\n"
            f"    {realm} = {{\n"
            f"        kdc = {self.kdc}\n"
            f"        admin_server = {self.kdc}\n"
            "    }\n\n"
            "[domain_realm]\n"
            f"    .{domain} = {realm}\n"
            f"    {domain} = {realm}\n"
        )
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", prefix="krb5_", suffix=".conf") as handle:
            handle.write(config)
            return handle.name

    def _build_env(self, ticket_cache: str, krb5_config: str) -> Dict[str, str]:
        env = os.environ.copy()
        env["KRB5CCNAME"] = ticket_cache
        env["KRB5_CONFIG"] = krb5_config
        if self.ldap_gssapi_service_host:
            env["SASL_NOCANON"] = "on"
        return env

    def _build_ldapsearch_uri(self) -> str:
        if not self.ldap_gssapi_service_host:
            return self.ldap_server

        parsed = urlparse(self.ldap_server)
        if not parsed.scheme or not parsed.netloc:
            return self.ldap_server

        host = self.ldap_gssapi_service_host
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"

        if parsed.username:
            credentials = parsed.username
            if parsed.password:
                credentials = f"{credentials}:{parsed.password}"
            host = f"{credentials}@{host}"

        return urlunparse(parsed._replace(netloc=host))

    def _build_ldapsearch_command(self, username: str) -> list[str]:
        safe_username = escape_filter_chars(username)
        return [
            "ldapsearch",
            "-LLL",
            "-N",
            "-Y",
            "GSSAPI",
            "-H",
            self._build_ldapsearch_uri(),
            "-b",
            self.base_dn,
            f"(sAMAccountName={safe_username})",
            "displayName",
            "mail",
            "memberOf",
        ]

    def get_ticket(self, username: str, password: str, ticket_cache: str, krb5_config: str) -> bool:
        try:
            principal = f"{username}@{self.realm}"
            result = subprocess.run(
                ["kinit", principal],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10,
                env=self._build_env(ticket_cache, krb5_config),
            )
            if result.returncode != 0:
                logger.error("kinit failed for %s: %s", username, result.stderr.strip())
                return False
            return True
        except Exception:
            logger.exception("Kerberos ticket error for %s", username)
            return False

    def get_service_ticket(self, principal: str, keytab_path: str, ticket_cache: str, krb5_config: str) -> bool:
        try:
            result = subprocess.run(
                ["kinit", "-k", "-t", keytab_path, principal],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._build_env(ticket_cache, krb5_config),
            )
            if result.returncode != 0:
                logger.error("kinit -k failed for service principal %s: %s", principal, result.stderr.strip())
                return False
            return True
        except Exception:
            logger.exception("Kerberos service ticket error for %s", principal)
            return False

    def destroy_ticket(self, ticket_cache: str, krb5_config: str) -> None:
        try:
            subprocess.run(
                ["kdestroy"],
                capture_output=True,
                timeout=5,
                env=self._build_env(ticket_cache, krb5_config),
                check=False,
            )
        except Exception as exc:
            logger.warning("Failed to destroy Kerberos ticket: %s", exc)

        for path in (ticket_cache, krb5_config):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    logger.warning("Failed to remove temporary Kerberos file %s: %s", path, exc)

    def get_user_info_from_ldap(self, username: str, ticket_cache: str, krb5_config: str) -> Optional[Dict[str, Any]]:
        cmd = self._build_ldapsearch_command(username)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._build_env(ticket_cache, krb5_config),
            )
            if result.returncode != 0:
                logger.error("ldapsearch failed for %s: %s", username, result.stderr.strip())
                return None
            return self._parse_ldap_output(result.stdout, username)
        except Exception:
            logger.exception("LDAP lookup failed for %s", username)
            return None

    def _build_fallback_identity(self, username: str) -> Dict[str, Any]:
        return build_identity_contract(username, email=f"{normalize_username(username)}@{self.ldap_domain}")

    def resolve_identity_via_service_credentials(
        self,
        username: str,
        *,
        service_principal: Optional[str] = None,
        keytab_path: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = normalize_username(username)
        principal = (service_principal or settings.SSO_SERVICE_PRINCIPAL).strip()
        keytab = (keytab_path or settings.SSO_KEYTAB_PATH).strip()
        if not normalized or not principal or not keytab:
            return None
        if not os.path.exists(keytab):
            logger.error("SSO keytab path %s is missing", keytab)
            return None

        ticket_cache = self._create_ticket_cache(normalized)
        krb5_config = self._create_krb5_config()
        try:
            if not self.get_service_ticket(principal, keytab, ticket_cache, krb5_config):
                return None

            user_info = self.get_user_info_from_ldap(normalized, ticket_cache, krb5_config)
            if not user_info:
                return None
            return enrich_identity_session_fields(user_info, auth_source=AUTH_SOURCE_SSO)
        finally:
            self.destroy_ticket(ticket_cache, krb5_config)

    def _parse_ldap_output(self, output: str, username: str) -> Dict[str, Any]:
        user_info = self._build_fallback_identity(username)
        display_name = re.search(r"displayName::? (.*?)(?=\n\S|\Z)", output, re.DOTALL)
        email = re.search(r"mail::? (.*?)(?=\n\S|\Z)", output, re.DOTALL)
        groups = re.findall(r"memberOf::? (.*?)(?=\n\S|\Z)", output, re.DOTALL)

        if display_name:
            user_info["display_name"] = display_name.group(1).strip()
        if email:
            user_info["email"] = email.group(1).strip()

        user_info["groups"] = []
        for group in groups:
            match = re.search(r"CN=([^,]+)", group)
            if match:
                user_info["groups"].append(match.group(1))

        return build_identity_contract(
            user_info["username"],
            display_name=user_info.get("display_name"),
            email=user_info.get("email"),
            groups=user_info.get("groups"),
            canonical_principal=user_info.get("canonical_principal"),
            auth_source=user_info.get("auth_source", AUTH_SOURCE_PASSWORD),
            auth_time=user_info.get("auth_time"),
            directory_checked_at=user_info.get("directory_checked_at"),
            identity_version=user_info.get("identity_version"),
        )


kerberos_auth = KerberosAuth()


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if "\\" in normalized:
        normalized = normalized.split("\\", 1)[1]
    if "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    normalized = normalized.strip().lower()
    if not normalized or not USERNAME_RE.fullmatch(normalized):
        return ""
    return normalized


def _coerce_identity_timestamp(value: Any, default: int) -> int:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def current_identity_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def normalize_auth_source(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {AUTH_SOURCE_PASSWORD, AUTH_SOURCE_SSO}:
        return normalized
    return AUTH_SOURCE_PASSWORD


def normalize_groups(groups: Any) -> list[str]:
    normalized_groups: list[str] = []
    seen: set[str] = set()
    for group in groups or []:
        candidate = str(group).strip()
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_groups.append(candidate)
    return normalized_groups or ["domain_users"]


def canonical_principal_for_username(username: str) -> str:
    normalized = normalize_username(username)
    if not normalized:
        return ""
    return f"{normalized}@{settings.KERBEROS_REALM.upper()}"


def build_identity_contract(
    username: str,
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    groups: Any = None,
    canonical_principal: Optional[str] = None,
    auth_source: str = AUTH_SOURCE_PASSWORD,
    auth_time: Optional[int] = None,
    directory_checked_at: Optional[int] = None,
    identity_version: Optional[int] = None,
) -> Dict[str, Any]:
    normalized = normalize_username(username)
    now = current_identity_timestamp()
    effective_auth_time = _coerce_identity_timestamp(auth_time, now)
    return {
        "username": normalized,
        "canonical_principal": (canonical_principal or canonical_principal_for_username(normalized)).strip(),
        "display_name": (display_name or normalized.capitalize()).strip() if normalized else "",
        "email": (email or f"{normalized}@{settings.LDAP_DOMAIN}").strip() if normalized else "",
        "groups": normalize_groups(groups),
        "auth_source": normalize_auth_source(auth_source),
        "auth_time": effective_auth_time,
        "directory_checked_at": _coerce_identity_timestamp(directory_checked_at, effective_auth_time),
        "identity_version": _coerce_identity_timestamp(identity_version, IDENTITY_VERSION),
    }


def _groups_lower(user_info: Dict[str, Any]) -> list[str]:
    return [group.lower() for group in user_info.get("groups", [])]


def _normalize_policy_category_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _policy_category_sort_key(category_path: Path) -> tuple[int, str]:
    category_name = category_path.name.lower()
    return (MODEL_POLICY_CATEGORY_ORDER.get(category_name, len(MODEL_POLICY_CATEGORY_ORDER)), category_name)


def get_configured_model_access_groups_for_category(category_key: str) -> set[str]:
    settings_attr = MODEL_POLICY_CATEGORY_GROUP_MAPPING.get(category_key)
    if not settings_attr:
        return set()
    return set(getattr(settings, settings_attr, ()) or ())


def _normalize_registry_policy_tier(value: Any) -> str:
    normalized = _normalize_policy_category_name(value)
    if normalized in MODEL_POLICY_CATEGORY_ORDER:
        return normalized
    return ""


def load_model_registry_catalog(registry_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    root = Path(registry_path or settings.model_registry_path)
    if not root.exists() or not root.is_file():
        logger.error("Model registry file %s is missing or invalid", root)
        return {}

    try:
        payload = json.loads(root.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load model registry file %s: %s", root, exc)
        return {}

    model_entries = payload.get("models")
    if not isinstance(payload, dict) or not isinstance(model_entries, list):
        logger.error("Model registry file %s does not contain a valid 'models' array", root)
        return {}

    catalog: Dict[str, Dict[str, Any]] = {}
    for model_entry in model_entries:
        if not isinstance(model_entry, dict):
            continue

        model_key = str(model_entry.get("install_name") or "").strip()
        if not model_key:
            continue

        sort_order = model_entry.get("installer_order")
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            sort_order = len(MODEL_POLICY_CATEGORY_ORDER) * 1000

        catalog[model_key] = {
            "model_key": model_key,
            "display_name": str(model_entry.get("display_name") or model_key).strip() or model_key,
            "category": _normalize_registry_policy_tier(model_entry.get("policy_tier")),
            "enabled_for_validation_user": bool(model_entry.get("enabled_for_validation_user", False)),
            "requires_gpu": bool(model_entry.get("gpu_required", False)),
            "experimental": bool(model_entry.get("experimental", False)),
            "sort_order": sort_order,
        }

    return catalog


def _iter_registry_models(
    registry_catalog: Dict[str, Dict[str, Any]],
    *,
    category_keys: Optional[set[str]] = None,
    validation_only: bool = False,
) -> list[Dict[str, Any]]:
    models: list[Dict[str, Any]] = []
    for model_entry in registry_catalog.values():
        category_key = model_entry.get("category") or ""
        if category_keys is not None and category_key not in category_keys:
            continue
        if validation_only and not model_entry.get("enabled_for_validation_user", False):
            continue
        models.append(model_entry)

    return sorted(
        models,
        key=lambda item: (
            MODEL_POLICY_CATEGORY_ORDER.get(item.get("category") or "", len(MODEL_POLICY_CATEGORY_ORDER)),
            int(item.get("sort_order", len(MODEL_POLICY_CATEGORY_ORDER) * 1000)),
            str(item.get("model_key") or ""),
        ),
    )


def _resolve_model_access_entry(
    live_model: Dict[str, str],
    *,
    model_key: str,
    category_key: str,
    policy_model: Optional[Dict[str, Any]] = None,
    registry_model: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    effective_policy = policy_model or {}
    effective_registry = registry_model or {}
    display_name = (
        str(effective_policy.get("display_name") or effective_registry.get("display_name") or model_key).strip() or model_key
    )

    merged_model = dict(live_model)
    merged_model.setdefault("name", display_name)
    merged_model["category"] = category_key or effective_policy.get("category") or effective_registry.get("category") or ""
    merged_model["policy_display_name"] = display_name
    merged_model["requires_gpu"] = bool(
        effective_policy.get("requires_gpu", effective_registry.get("requires_gpu", False))
    )
    merged_model["experimental"] = bool(
        effective_policy.get("experimental", effective_registry.get("experimental", False))
    )
    return merged_model


def is_validation_user(user_info: Dict[str, Any]) -> bool:
    configured_validation_user = normalize_username(getattr(settings, "INSTALL_TEST_USER", ""))
    if not configured_validation_user:
        return False
    return normalize_username(str(user_info.get("username") or "")) == configured_validation_user


def load_model_policy_catalog(policy_root: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    root = Path(policy_root or settings.model_policy_dir)
    if not root.exists() or not root.is_dir():
        logger.error("Model policy directory %s is missing or invalid", root)
        return {}

    catalog: Dict[str, Dict[str, Any]] = {}
    for category_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=_policy_category_sort_key):
        policy_path = category_dir / MODEL_POLICY_FILENAME
        if not policy_path.is_file():
            logger.warning("Skipping model policy category %s because %s is missing", category_dir.name, policy_path.name)
            continue

        try:
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load model policy file %s: %s", policy_path, exc)
            continue

        if not isinstance(payload, dict):
            logger.error("Skipping model policy file %s because it does not contain a JSON object", policy_path)
            continue

        category = _normalize_policy_category_name(payload.get("category") or category_dir.name)
        if not category or category != category_dir.name.lower():
            logger.error("Skipping model policy file %s because category does not match folder name", policy_path)
            continue

        if payload.get("enabled", True) is False:
            continue

        models: Dict[str, Dict[str, Any]] = {}
        for model_entry in payload.get("models", []):
            if not isinstance(model_entry, dict):
                continue
            if model_entry.get("enabled", True) is False:
                continue

            model_key = str(model_entry.get("model_key") or "").strip()
            if not model_key:
                continue

            models[model_key] = {
                "model_key": model_key,
                "display_name": str(model_entry.get("display_name") or model_key).strip() or model_key,
                "requires_gpu": bool(model_entry.get("requires_gpu", False)),
                "experimental": bool(model_entry.get("experimental", False)),
                "category": category,
            }

        if not models:
            logger.warning("Skipping model policy category %s because it has no enabled models", category)
            continue

        catalog[category] = {
            "category": category,
            "display_name": str(payload.get("display_name") or category_dir.name).strip() or category_dir.name,
            "models": models,
        }

    return catalog


def get_allowed_model_categories_for_user(
    user_info: Dict[str, Any],
    policy_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
    registry_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
) -> list[str]:
    catalog = policy_catalog or load_model_policy_catalog()
    if not catalog:
        return []

    if is_validation_user(user_info):
        registry = registry_catalog if registry_catalog is not None else load_model_registry_catalog()
        if registry:
            validation_categories = {
                str(model_entry.get("category") or "")
                for model_entry in registry.values()
                if model_entry.get("enabled_for_validation_user", False)
            }
            if validation_categories:
                return [category_key for category_key in catalog.keys() if category_key in validation_categories]
        return list(catalog.keys())

    groups_lower = set(_groups_lower(user_info))
    allowed_categories: list[str] = []
    for category_key, category_policy in catalog.items():
        if category_key == MODEL_POLICY_GENERAL_CATEGORY:
            allowed_categories.append(category_key)
            continue
        configured_groups = get_configured_model_access_groups_for_category(category_key)
        if configured_groups and configured_groups & groups_lower:
            allowed_categories.append(category_key)
    return allowed_categories


def enrich_identity_session_fields(
    user_info: Dict[str, Any],
    *,
    auth_source: str = AUTH_SOURCE_PASSWORD,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    base_identity = build_identity_contract(
        user_info.get("username", ""),
        display_name=user_info.get("display_name"),
        email=user_info.get("email"),
        groups=user_info.get("groups"),
        canonical_principal=user_info.get("canonical_principal"),
        auth_source=user_info.get("auth_source") or auth_source,
        auth_time=_coerce_identity_timestamp(user_info.get("auth_time"), now_ts or current_identity_timestamp()),
        directory_checked_at=user_info.get("directory_checked_at"),
        identity_version=user_info.get("identity_version"),
    )
    return {
        **base_identity,
        **user_info,
        "username": base_identity["username"],
        "canonical_principal": base_identity["canonical_principal"],
        "display_name": base_identity["display_name"],
        "email": base_identity["email"],
        "groups": base_identity["groups"],
        "auth_source": base_identity["auth_source"],
        "auth_time": base_identity["auth_time"],
        "directory_checked_at": base_identity["directory_checked_at"],
        "identity_version": base_identity["identity_version"],
    }


def get_allowed_models_for_user(
    user_info: Dict[str, Any],
    available_models: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, str]]:
    models = available_models or settings.get_available_models()
    if not models:
        return {}

    policy_catalog = load_model_policy_catalog()
    if not policy_catalog:
        logger.error(
            "Model policy catalog unavailable or empty; denying model access for user %s",
            user_info.get("username", "unknown"),
        )
        return {}

    registry_catalog = load_model_registry_catalog()
    validation_mode = is_validation_user(user_info) and bool(registry_catalog)

    allowed_models: Dict[str, Dict[str, str]] = {}
    if validation_mode:
        for registry_model in _iter_registry_models(registry_catalog, validation_only=True):
            model_key = str(registry_model.get("model_key") or "").strip()
            if not model_key:
                continue
            live_model = models.get(model_key)
            if live_model is None:
                continue

            category_key = str(registry_model.get("category") or "").strip()
            model_policy = {}
            if category_key:
                model_policy = policy_catalog.get(category_key, {}).get("models", {}).get(model_key, {})

            allowed_models[model_key] = _resolve_model_access_entry(
                live_model,
                model_key=model_key,
                category_key=category_key,
                policy_model=model_policy,
                registry_model=registry_model,
            )
    else:
        allowed_categories = get_allowed_model_categories_for_user(user_info, policy_catalog, registry_catalog)
        if not allowed_categories:
            logger.warning(
                "No model policy categories are available for user %s",
                user_info.get("username", "unknown"),
            )
            return {}

        if registry_catalog:
            for registry_model in _iter_registry_models(registry_catalog, category_keys=set(allowed_categories)):
                model_key = str(registry_model.get("model_key") or "").strip()
                if not model_key:
                    continue
                live_model = models.get(model_key)
                if live_model is None:
                    continue

                category_key = str(registry_model.get("category") or "").strip()
                model_policy = policy_catalog.get(category_key, {}).get("models", {}).get(model_key, {})
                allowed_models[model_key] = _resolve_model_access_entry(
                    live_model,
                    model_key=model_key,
                    category_key=category_key,
                    policy_model=model_policy,
                    registry_model=registry_model,
                )
        else:
            for category_key in allowed_categories:
                category_policy = policy_catalog.get(category_key, {})
                for model_key, model_policy in category_policy.get("models", {}).items():
                    live_model = models.get(model_key)
                    if live_model is None:
                        continue
                    allowed_models[model_key] = _resolve_model_access_entry(
                        live_model,
                        model_key=model_key,
                        category_key=category_key,
                        policy_model=model_policy,
                    )

    if not allowed_models:
        logger.warning(
            "No policy-approved live models remain for user %s after filtering",
            user_info.get("username", "unknown"),
        )
        return {}

    return allowed_models


def get_model_for_user(user_info: Dict[str, Any]) -> Dict[str, str]:
    available_models = settings.get_available_models()
    allowed_models = get_allowed_models_for_user(user_info, available_models)
    if not allowed_models:
        placeholder_key = settings.DEFAULT_MODEL or "llm-unavailable"
        logger.error("No LLM models available while assigning a model to user %s", user_info["username"])
        return {
            "name": placeholder_key,
            "description": "LLM runtime unavailable",
            "key": placeholder_key,
            "status": "unavailable",
        }

    selected_key = settings.pick_available_model(allowed_models) or next(iter(allowed_models.keys()))
    model_info = allowed_models[selected_key]
    logger.info("User %s assigned model %s", user_info["username"], model_info["name"])
    return {
        "name": model_info["name"],
        "description": model_info["description"],
        "key": selected_key,
        "status": model_info.get("status", "active"),
    }


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    issued_at = datetime.now(timezone.utc)
    expire = issued_at + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire, "iat": issued_at, "jti": to_encode.get("jti") or uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def extract_bearer_token(raw_token: Optional[str]) -> Optional[str]:
    if not raw_token:
        return None
    return raw_token.replace("Bearer ", "") if raw_token.startswith("Bearer ") else raw_token


def token_revocation_key(jti: str) -> str:
    return f"{TOKEN_REVOKE_PREFIX}:{jti}"


async def revoke_token(redis_client: Any, raw_token: Optional[str]) -> bool:
    token = extract_bearer_token(raw_token)
    if redis_client is None or not token:
        return False

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        logger.warning("Unable to revoke JWT: %s", exc)
        return False

    jti = payload.get("jti")
    exp = int(payload.get("exp") or 0)
    if not jti or exp <= 0:
        return False

    ttl = max(1, exp - int(datetime.now(timezone.utc).timestamp()))
    await redis_client.set(token_revocation_key(jti), "1", ex=ttl)
    return True


async def is_token_revoked(redis_client: Any, payload: Dict[str, Any]) -> bool:
    jti = payload.get("jti")
    if not jti:
        return True
    return bool(await redis_client.exists(token_revocation_key(jti)))


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[Dict[str, Any]]:
    token: Optional[str] = None

    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        token = extract_bearer_token(cookie_token)

    if not token and credentials:
        if (credentials.scheme or "").lower() != "bearer":
            logger.warning("Rejected unsupported authorization scheme %s", credentials.scheme)
            return None
        token = credentials.credentials

    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") == "refresh":
            return None

        gateway = getattr(request.app.state, "llm_gateway", None)
        redis_client = getattr(gateway, "redis", None)
        if redis_client is None:
            logger.error("Authentication backend unavailable: revocation store is offline")
            return None
        if await is_token_revoked(redis_client, payload):
            logger.warning("Rejected revoked JWT for subject %s", payload.get("sub"))
            return None

        username = payload.get("sub")
        if not username:
            return None

        user_info = {
            "username": username,
            "display_name": payload.get("display_name", username),
            "email": payload.get("email", f"{username}@{settings.LDAP_DOMAIN}"),
            "groups": payload.get("groups", []),
            "model": payload.get("model", settings.DEFAULT_MODEL or "phi3:mini"),
            "model_description": payload.get("model_description", "Модель по умолчанию"),
            "model_key": payload.get("model_key", payload.get("model", settings.DEFAULT_MODEL or "phi3:mini")),
        }
        return enrich_identity_session_fields(
            {
                **user_info,
                "canonical_principal": payload.get("canonical_principal"),
                "auth_source": payload.get("auth_source"),
                "auth_time": payload.get("auth_time"),
                "directory_checked_at": payload.get("directory_checked_at"),
                "identity_version": payload.get("identity_version"),
            }
        )
    except JWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        return None


async def get_current_user_required(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

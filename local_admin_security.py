import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict


LOCAL_ADMIN_AUTH_SOURCE = "local_admin"
LOCAL_ADMIN_HASH_SCHEME = "pbkdf2_sha256"
LOCAL_ADMIN_HASH_ITERATIONS = 600_000
LOCAL_ADMIN_HASH_SALT_BYTES = 16
LOCAL_ADMIN_STATE_REDIS_KEY = "auth:local_admin:state:v1"


def build_local_admin_password_hash(password: str) -> str:
    secret = str(password or "")
    if not secret:
        raise ValueError("local admin password cannot be empty")

    salt = secrets.token_bytes(LOCAL_ADMIN_HASH_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, LOCAL_ADMIN_HASH_ITERATIONS)
    return "$".join(
        (
            LOCAL_ADMIN_HASH_SCHEME,
            str(LOCAL_ADMIN_HASH_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_local_admin_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, raw_iterations, salt_b64, digest_b64 = str(stored_hash or "").split("$", 3)
        if scheme != LOCAL_ADMIN_HASH_SCHEME:
            return False
        iterations = int(raw_iterations)
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        expected_digest = base64.b64decode(digest_b64.encode("ascii"), validate=True)
    except (ValueError, TypeError, base64.binascii.Error):
        return False

    candidate_digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate_digest, expected_digest)


def build_local_admin_state_revision(state: Dict[str, Any]) -> str:
    payload = {
        "base_env_revision": str(state.get("base_env_revision") or ""),
        "bootstrap_required": bool(state.get("bootstrap_required", False)),
        "enabled": bool(state.get("enabled", False)),
        "force_rotate": bool(state.get("force_rotate", False)),
        "password_hash": str(state.get("password_hash") or ""),
        "runtime_override": bool(state.get("runtime_override", False)),
        "username": str(state.get("username") or ""),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


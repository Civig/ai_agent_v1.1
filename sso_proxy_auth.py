import base64
import binascii
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from auth_kerberos import AUTH_SOURCE_SSO, build_identity_contract, enrich_identity_session_fields, kerberos_auth, normalize_username, settings

logger = logging.getLogger(__name__)

try:
    import gssapi  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised indirectly via runtime gating
    gssapi = None


def _negotiate_header(token: Optional[bytes] = None) -> str:
    if not token:
        return "Negotiate"
    return f"Negotiate {base64.b64encode(token).decode('ascii')}"


def _header_safe_value(value: Optional[str]) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    try:
        candidate.encode("ascii")
    except UnicodeEncodeError:
        return ""
    return candidate


def _build_identity_headers(user_info: Dict[str, Any]) -> Dict[str, str]:
    identity = enrich_identity_session_fields(user_info, auth_source=AUTH_SOURCE_SSO)
    headers = {
        "X-Authenticated-User": identity["username"],
        "X-Authenticated-Principal": _header_safe_value(identity["canonical_principal"]),
        "X-Authenticated-Email": _header_safe_value(identity["email"]),
        "X-Authenticated-Groups": json.dumps(identity.get("groups", []), ensure_ascii=True, separators=(",", ":")),
    }
    display_name = _header_safe_value(identity.get("display_name"))
    if display_name:
        headers["X-Authenticated-Name"] = display_name
    return headers


def _resolve_sso_identity(principal: str) -> Dict[str, Any]:
    normalized_username = normalize_username(principal)
    if not normalized_username:
        raise ValueError("Unable to normalize Kerberos principal")

    resolved_identity = kerberos_auth.resolve_identity_via_service_credentials(normalized_username)
    if resolved_identity:
        return enrich_identity_session_fields(resolved_identity, auth_source=AUTH_SOURCE_SSO)

    return enrich_identity_session_fields(
        build_identity_contract(
            normalized_username,
            auth_source=AUTH_SOURCE_SSO,
        ),
        auth_source=AUTH_SOURCE_SSO,
    )


def validate_negotiate_request_headers(request: Request) -> str:
    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        raise HTTPNegotiateChallenge()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "negotiate" or not token.strip():
        raise HTTPNegotiateChallenge()
    return token.strip()


class HTTPNegotiateChallenge(Exception):
    def __init__(self, *, token: Optional[bytes] = None, status_code: int = 401):
        self.header_value = _negotiate_header(token)
        self.status_code = status_code
        super().__init__("Kerberos negotiation required")


def _build_gssapi_context():
    if gssapi is None:
        raise RuntimeError("gssapi module is unavailable")

    if settings.SSO_KEYTAB_PATH:
        os.environ["KRB5_KTNAME"] = settings.SSO_KEYTAB_PATH

    credentials = gssapi.Credentials(usage="accept")
    return gssapi.SecurityContext(creds=credentials)


def authenticate_negotiate_token(token_b64: str) -> tuple[str, Optional[bytes]]:
    try:
        token_bytes = base64.b64decode(token_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPNegotiateChallenge() from exc

    context = _build_gssapi_context()
    output_token = context.step(token_bytes)
    if not context.complete:
        raise HTTPNegotiateChallenge(token=output_token)

    initiator = getattr(context, "initiator_name", None)
    if initiator is None:
        raise ValueError("Kerberos initiator name is unavailable")

    return str(initiator), output_token


def create_app() -> FastAPI:
    app = FastAPI(title="Corporate AI Assistant SSO Proxy Auth", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def health_live() -> Response:
        status_code = 200 if settings.SSO_ENABLED and settings.TRUSTED_AUTH_PROXY_ENABLED else 503
        return JSONResponse(
            {
                "status": "ok" if status_code == 200 else "disabled",
                "sso_enabled": settings.SSO_ENABLED,
                "trusted_proxy_enabled": settings.TRUSTED_AUTH_PROXY_ENABLED,
                "gssapi_available": gssapi is not None,
            },
            status_code=status_code,
        )

    @app.get("/validate")
    async def validate(request: Request) -> Response:
        if not settings.SSO_ENABLED or not settings.TRUSTED_AUTH_PROXY_ENABLED:
            return JSONResponse({"error": "Trusted proxy SSO is disabled"}, status_code=403)
        if not settings.SSO_SERVICE_PRINCIPAL or not settings.SSO_KEYTAB_PATH:
            logger.error("Trusted proxy SSO is enabled but service principal or keytab path is missing")
            return JSONResponse({"error": "Trusted proxy SSO is not configured"}, status_code=503)
        if not os.path.exists(settings.SSO_KEYTAB_PATH):
            logger.error("Trusted proxy SSO keytab %s is missing", settings.SSO_KEYTAB_PATH)
            return JSONResponse({"error": "Trusted proxy SSO keytab is missing"}, status_code=503)
        if gssapi is None:
            logger.error("Trusted proxy SSO requested but python-gssapi is unavailable")
            return JSONResponse({"error": "Trusted proxy SSO runtime is unavailable"}, status_code=503)

        try:
            token_b64 = validate_negotiate_request_headers(request)
            principal, response_token = authenticate_negotiate_token(token_b64)
            identity = _resolve_sso_identity(principal)
            headers = _build_identity_headers(identity)
            if response_token:
                headers["WWW-Authenticate"] = _negotiate_header(response_token)
            return Response(status_code=204, headers=headers)
        except HTTPNegotiateChallenge as challenge:
            return Response(status_code=challenge.status_code, headers={"WWW-Authenticate": challenge.header_value})
        except Exception:
            logger.exception("Trusted proxy SSO validation failed")
            return JSONResponse({"error": "Trusted proxy SSO validation failed"}, status_code=500)

    return app


app = create_app()

# Security Baseline

## Scope

This document describes the current security baseline of Corporate AI Assistant as implemented in the repository today. It is not a claim of full enterprise security coverage.

The current security posture is best understood as:

- internal deployment baseline
- pilot-ready with operator hardening
- not a substitute for organization-wide security controls

## Deployment Assumptions

The repository is designed for internal deployment behind organization-managed network controls. Operators are expected to provide:

- trusted network placement
- proper host hardening
- organization-approved secrets management practices
- certificate replacement for production use

## Authentication and Session Model

### What is implemented

- login flow backed by Kerberos and LDAP
- JWT-based access and refresh tokens
- cookies for token transport
- logout revocation through Redis-backed token state
- login rate limiting
- fail-closed behavior when the auth backend is unavailable
- proxy-terminated AD SSO session issuance through a dedicated trusted reverse-proxy path
- refresh-token rotation on `/api/refresh`
- explicit session metadata in token claims:
  - `auth_source=password`
  - `auth_source=sso`
  - `auth_time`
  - `directory_checked_at`
  - `identity_version`
  - `canonical_principal`

### Session and CSRF baseline

The application currently includes:

- HTTP cookie-based session transport
- CSRF token validation for modifying requests
- cookie configuration controlled through environment variables
- a narrow bearer-only CSRF bypass for non-cookie API clients
- explicit rejection of reserved proxy-auth headers unless trusted proxy SSO mode is enabled
- reserved proxy-auth headers are accepted only on the dedicated SSO entry path (`/auth/sso/login`) and only from a trusted proxy source
- the main FastAPI app still rejects raw `Authorization: Negotiate ...` as an authentication path
- startup validation for environment secrets and proxy-boundary settings:
  - placeholder passwords embedded in `REDIS_URL` and `PERSISTENT_DB_URL` are rejected
  - explicit passwords are required for non-local Redis/PostgreSQL deployments
  - `TRUSTED_PROXY_SOURCE_CIDRS` must be valid and is mandatory when trusted-proxy SSO is enabled
- Uvicorn proxy-header trust no longer relies on a wildcard allowlist; it is configured through `FORWARDED_ALLOW_IPS`

### Current SSO implementation status

The repository now includes an actual SSO path, but only under a strict trusted-proxy contract:

- password login remains active as a fallback
- SSO is disabled by default
- SSO works only when both `SSO_ENABLED=true` and `TRUSTED_AUTH_PROXY_ENABLED=true`
- Uvicorn must trust forwarded headers only from the reverse-proxy hop; this is configured through `FORWARDED_ALLOW_IPS`
- `TRUSTED_PROXY_SOURCE_CIDRS` must explicitly list the source addresses/CIDRs of the reverse proxy hop that reaches `app`
- the browser-facing Kerberos/SPNEGO negotiation is terminated before the main app
- the main app only accepts proxy-validated identity headers on the dedicated SSO entry path
- the main app does not accept arbitrary identity headers on regular routes
- model access for SSO sessions uses the same `.env` group mapping and explicit model catalog as password sessions

### Current limitation

- refresh still preserves the last directory-derived identity snapshot instead of re-checking AD on every refresh
- SSO requires real infrastructure prerequisites:
  - trusted HTTPS FQDN
  - valid `HTTP/<fqdn>@REALM` SPN
  - service keytab mounted into `deploy/sso/`
  - a correct `FORWARDED_ALLOW_IPS` value matching the reverse-proxy source IP/CIDR that reaches `app`
  - a correct `TRUSTED_PROXY_SOURCE_CIDRS` value matching the reverse-proxy addresses on the hop to `app`
  - domain-joined clients and browser trust-zone configuration
- app logout only clears the local application session; it does not claim to log the user out of Windows, Kerberos, or the browser's SPNEGO state
- model access control now uses an explicit folder-based policy catalog under `model_policies/`, but it is still a simple category policy, not full enterprise RBAC
- AD group names for `coding` and `admin` categories are no longer hardcoded in runtime code; they are supplied through `.env` as `MODEL_ACCESS_CODING_GROUPS` and `MODEL_ACCESS_ADMIN_GROUPS`
- users still choose the model manually, but only from the policy-approved visible set
- `general` access is granted to authenticated users, while `coding` and `admin` depend on exact group matches from `.env`
- policy files are metadata only; they are not model weights and they do not enable SSO by themselves

### Important operational note

The Kerberos/LDAP path depends on hostname and SPN consistency. Misaligned DNS/SPN configuration can break authentication even when credentials are valid.

## Transport Security

### What is implemented

- Nginx as the HTTPS ingress
- TLS certificate support in the deployment layout
- dedicated `sso-proxy` helper support for trusted reverse-proxy Kerberos/SPNEGO validation

### Current limitation

The installer generates self-signed certificates by default. This is acceptable for internal smoke testing and early pilots, but it is not the recommended production posture. Kerberos/SPNEGO SSO should be used with a trusted certificate on the real FQDN.

## Redis and Runtime Boundary

### What is implemented

- Redis is intended to stay on the internal Compose network
- the public entrypoint is Nginx, not Redis or the FastAPI container directly
- runtime health and queue state are not exposed as a public database API

### Current limitation

- Redis is single-node by default
- no HA Redis profile is shipped yet

## Supply-chain baseline

### What is implemented

- Docker builds now rely on pinned [requirements.lock](../requirements.lock), not only on loose `requirements.txt`
- the `Dockerfile` uses a pinned Python base image digest
- Compose external images for `redis`, `postgres`, `ollama`, and `nginx` now use pinned baseline references instead of `latest`

### Current limitation

- this is a minimal reproducibility baseline, not a full software supply-chain framework
- host apt repositories, Docker Engine packages, and external installer downloads still depend on operator-controlled infrastructure
- refreshing digests or the lock file remains an intentional operator/release task and must be re-validated

## Dashboard Telemetry Boundary

### What is implemented

- a read-only operator dashboard under `/admin/dashboard`
- dashboard API surfaces:
  - `/api/admin/dashboard/summary`
  - `/api/admin/dashboard/live`
  - `/api/admin/dashboard/history`
  - `/api/admin/dashboard/events`
- honest no-data / unavailable semantics for telemetry, GPU, and history
- the dashboard does not fabricate metrics or substitute missing telemetry with zeroes

### Current limitation

- the current dashboard access model remains a narrow env-driven operator gate (`ADMIN_DASHBOARD_USERS`), not production-ready RBAC
- dashboard payloads expose operational telemetry, history, and event context, so this surface should remain operator-only
- if SSO is expected to cover dashboard access, that still requires separate real-infrastructure validation

### Local break-glass admin

For emergency operator recovery, the runtime now supports a separate local break-glass admin path, but only as a controlled fallback for the dashboard surface:

- the local admin path is disabled by default with `LOCAL_ADMIN_ENABLED=false`
- the default username is `LOCAL_ADMIN_USERNAME=admin_ai`
- `.env` stores only `LOCAL_ADMIN_PASSWORD_HASH`; plaintext passwords are not used
- the installer-managed `.env` stores `LOCAL_ADMIN_PASSWORD_HASH` in compose-safe escaped `$$` form so Docker Compose does not mangle the hash on the transport boundary
- if the installer is not given an explicit password, it generates a one-time bootstrap secret and stores that plaintext only in a root-only `0600` host file
- while `LOCAL_ADMIN_FORCE_ROTATE=true` and `LOCAL_ADMIN_BOOTSTRAP_REQUIRED=true`, the first local-admin login can reach only the forced password rotation flow
- until rotation is completed, the local admin session cannot access `/admin/dashboard` or `/api/admin/dashboard/*`
- after forced rotation, the authenticated local-admin session can use the normal `GET/POST /admin/local/change-password` flow
- the normal change-password flow is available only to a valid local-admin session without pending rotation; anonymous requests and ordinary AD sessions are denied
- after a successful password change, the bootstrap secret is invalidated, the current local-admin session is logged out, and the older session revision is rejected fail-closed
- the local admin session uses separate cookies and a separate auth source, so it does not replace the ordinary chat/session flow
- login attempts, logout, forced rotation, and normal password change are logged without disclosing plaintext password or bootstrap-secret material
- `ADMIN_DASHBOARD_USERS` remains a separate ordinary-operator gate and is not replaced by the local-admin fallback path

### Standalone GPU Lab mode

For isolated GPU validation, the runtime also supports an explicit lab profile, but only as an intentionally insecure engineering mode:

- the default baseline remains enterprise: `INSTALL_PROFILE=enterprise`, `AUTH_MODE=ad`
- lab mode requires the explicit combination `INSTALL_PROFILE=standalone_gpu_lab`, `AUTH_MODE=lab_open`, and `LAB_OPEN_AUTH_ACK=true`
- if `AUTH_MODE=lab_open` is configured without that acknowledgment, startup fails fast
- ordinary authentication is disabled in that mode and the runtime uses a synthetic lab identity
- the dashboard shows an explicit warning whenever `lab_open` is active
- this mode must not be exposed to production users or the public Internet without strict network isolation

## Upload and File Security Baseline

### What is implemented

The current upload path includes:

- allowlisted file extensions
- allowlisted MIME/content-type mapping
- compatibility fallback for empty or generic content-type values
- safe filename normalization
- file size limits
- file count limits
- temporary staging instead of a durable attachment store
- cleanup of temporary upload artifacts

Supported upload types today:

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### What this baseline is meant to stop

- obvious unsupported file uploads
- obvious extension-only abuse
- common content-type mismatch cases
- path traversal through filenames

### What is not implemented

- antivirus scanning
- sandbox execution
- file signature sniffing with deep type verification
- DLP or content classification
- durable attachment access-control model

## Prompt and Model Safety Baseline

### What is implemented

- prompt injection filtering on direct user prompts
- context governance for history, document context, and total prompt size
- grounded document prompts for file-chat
- anti-hallucination response framing for document-based answers

### Current limitation

- this is prompt-layer risk reduction, not a full model safety system
- no external policy engine is integrated

## Logging and Data Exposure Baseline

### What is implemented

- structured operational logs
- upload rejection logging without file content
- parse/queue/inference/terminal timing logs
- avoidance of raw document preview logging in the current file-chat observability path

### What operators should still treat carefully

- logs can still contain usernames, model identifiers, and error metadata
- Redis contains live job state and chat history

## Known Security Gaps

The following areas are not fully implemented in this repository:

- external secret manager integration
- HA control plane
- centralized SIEM forwarding
- antivirus or sandbox-based file scanning
- fine-grained admin controls
- a production-ready dashboard role/claim model
- packaged compliance controls
- multi-layer content classification or DLP

## Pilot-Use Recommendations

Before a pilot or internal rollout:

- replace self-signed certificates with trusted TLS material
- rotate `SECRET_KEY` and `REDIS_PASSWORD`
- restrict host access and management access by policy
- validate AD hostname and SPN behavior with a smoke account
- validate the HTTP service principal and keytab before enabling SSO
- validate SSO in a domain-joined browser separately from the password fallback login
- validate at least one working Ollama model
- validate file-chat behavior with allowed file types
- if GPU is planned, validate host GPU container support separately before enabling the profile

## What to Treat as Planned or Operator-Owned

- centralized metrics and alerting
- HA Redis
- enterprise certificate lifecycle automation
- advanced malware scanning
- broader admin policy tooling

## Related Documents

- [README.md](../README.md)
- [Install Guide](INSTALL_en.md)
- [Architecture](ARCHITECTURE_en.md)
- [Administration and Operations](ADMIN_en.md)
- [Troubleshooting](TROUBLESHOOTING_en.md)

# Changelog

All notable changes to Corporate AI Assistant should be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

This section tracks the current release-candidate line for `v1.2.0`. The final release tag is created only after the final TEST VM validation pass.

### Added

- local break-glass admin path for operator recovery on `/admin/dashboard` and `/api/admin/dashboard/*`
- authenticated local-admin password-change flow on `GET/POST /admin/local/change-password`

### Changed

- Docker build and deploy reproducibility baseline now relies on pinned image digests plus `requirements.lock`
- installer model selection now uses a numeric multi-select flow and shows only installable models from the installer view
- model bootstrap now reports selected/successful/failed models more explicitly and keeps the bounded online-first contract
- release-facing documentation now treats `v1.1.0` as the earlier baseline and `main` as the current `v1.2.0` release-candidate line

### Fixed

- model bootstrap now uses a bounded timeout budget and clearer failure handling for online pull vs local fallback
- runtime model access and installer model catalog alignment now use the unified registry/catalog contract
- forwarded proxy trust no longer relies on a wildcard trust baseline
- dashboard access no longer falls back to a hardcoded operator user
- installer bootstrap invocation is aligned with the repository bootstrap script contract
- runtime health checks are aligned with the `start_app.py` startup path
- local-admin password hash transport is now compose-safe
- local-admin dashboard cookies now cover both the dashboard route and dashboard API surfaces

## [1.1.0] - 2026-03-28

### Changed

- release workspace prepared as a sanitized `ai_agent_v1.1` snapshot for future publication
- Russian documentation is treated as the primary operator-facing reference, with English documents kept in sync
- release-facing documentation now uses neutral repository placeholders instead of the previous published repository URL
- installer prompts are prepared for Russian-first bilingual operation with examples, without changing the validated install logic

### Fixed

- installer-managed `docker-compose.override.yml` no longer duplicates AD host aliases in `extra_hosts`
- login page template rendering now passes `request` explicitly to `TemplateResponse`
- LDAP GSSAPI runtime lookup now disables SASL canonicalization through `ldapsearch -N`
- chat page template rendering now passes `request` explicitly to `TemplateResponse`

### Added

- CPU/GPU routing readiness for chat jobs with explicit `target_kind`
- safe fallback from GPU-targeted routing to CPU when no GPU worker is active
- context governance for history, document context, and final prompt size
- async file-chat execution through the existing queue/worker lifecycle
- PDF parsing stabilization with a reproducible parser order
- upload security baseline for extension and MIME validation
- observability baseline for parse, queue wait, inference, and terminal job timing
- repository hygiene fix so `tests/test_*.py` files are no longer hidden by `.gitignore`
- bilingual documentation set in `docs/` for install, architecture, operations, troubleshooting, and security

### Changed

- file-chat is now handled through the queue/worker path instead of keeping generation in the app request path
- README has been rewritten as the main English GitHub entrypoint
- operational documentation now reflects the current Docker Compose deployment model and known limitations

### Fixed

- PDF processing now follows the parser path that is actually reproducible in the application runtime
- file uploads reject obvious type-confusion cases instead of trusting extensions alone
- observability and file-chat related tests are now visible to git and trackable

## [1.0.0] - 2026-03-11

### Added

- initial Docker Compose deployment for the Corporate AI Assistant stack
- FastAPI application with web chat interface
- Redis-backed control plane for authentication support and runtime state
- Kerberos and LDAP integration for Active Directory environments
- Ollama-based local inference runtime integration
- Nginx HTTPS ingress
- installer and helper scripts for Linux-based deployment

### Notes

- the repository was initially published as an internal/on-prem oriented deployment project
- later hardening, queue/runtime improvements, file-chat maturity, and documentation expansion are tracked in `Unreleased`

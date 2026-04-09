# Pilot Baseline

## Purpose

This document fixes the current pilot baseline candidate for Corporate AI Assistant as the source-of-truth reference point for the pilot.

## Exact baseline

- branch: `main`
- exact baseline SHA: `33960581772787b162a0885bc2181f650f22a168`
- short SHA: `3396058`
- baseline type: documentation/package baseline candidate for pilot review

## What is already implemented in this baseline

The current baseline already includes implemented and documented:

- the supported deployment path: Linux VM + Docker Compose + `install.sh`
- Kerberos + LDAP-backed password login
- the optional trusted reverse-proxy SSO path in runtime and docs
- normal web chat
- file-chat through the parser-stage path with `worker-parser` and shared staging
- the read-only operator dashboard with `summary/live/history/events`
- the Redis/PostgreSQL transitional conversation persistence baseline
- installer-driven `.env`, Kerberos, TLS, and stack bootstrap
- safe uninstall and the manifest-driven `factory-reset` uninstall path

Important baseline boundary:

- the dashboard access model still remains a narrow temporary operator gate and must not be described as production-ready RBAC

## What is confirmed at repository level

The repository already contains a synchronized code/docs baseline and recorded repo-level evidence for the key areas:

- install/persistence profile: `tests/test_install_postgres_profile.py`
- config/security guards: `tests/test_config_security_validation.py`
- trusted-proxy SSO preparation path: `tests/test_auth_sso_preparation.py`
- dashboard route/access/API/telemetry behavior:
  - `tests/test_admin_dashboard_route_regression.py`
  - `tests/test_admin_dashboard_access.py`
  - `tests/test_admin_dashboard_api.py`
  - `tests/test_dashboard_telemetry_logic.py`
- parser/file-chat async path:
  - `tests/test_parser_stage_runtime.py`
  - `tests/test_file_chat_worker.py`
  - `tests/test_file_chat_async_queue.py`
- GPU routing/fallback logic: `tests/test_gpu_routing.py`
- persistence groundwork/boundary/bootstrap:
  - `tests/test_conversation_persistence_groundwork.py`
  - `tests/test_conversation_persistence_bootstrap.py`
  - `tests/test_conversation_persistence_boundary.py`
  - `tests/test_app_persistence_startup.py`

This is evidence of the implemented repository baseline, but it is not a substitute for fresh install validation and not a substitute for real infrastructure validation.

## What is recorded as VM-level evidence

According to the current source of truth:

- `docs/SUPPORTED_OS.md` records a clean installer validation point on Ubuntu 24.04 for revision `eba7ea9` within the current release family
- the supported installer targets remain `Ubuntu 20.04+` and `Debian 11+`
- the exact current HEAD `3396058` is not newly claimed as freshly validated through a separate TEST VM install in this pilot package step

In other words:

- recorded validation evidence exists for the release family
- the current HEAD is treated as the baseline candidate
- fresh install re-validation of the exact current HEAD before a pilot freeze is still a separate step

## What still requires separate validation

The following items are not proven automatically and must not be implied:

- GPU readiness on a dedicated GPU host
- real-infrastructure trusted reverse-proxy SSO on the final FQDN/SPN/keytab path
- a production-grade dashboard access model
- the final authoritative PostgreSQL ownership cutover for conversation data without the Redis fallback bridge
- HA, external secret manager, and centralized SIEM/observability integrations

## What this baseline is meant to prove in the pilot

This pilot baseline is meant to prove that:

- the exact baseline SHA can be deployed through the supported path without changing runtime semantics
- the CPU-first on-prem baseline provides working login, normal chat, file-chat, and operator monitoring
- the install, acceptance, runbook, and handoff docs are sufficient for controlled pilot execution
- the baseline limitations are stated honestly and can be accepted before the pilot starts

## What this baseline does not prove

This baseline does not by itself prove:

- that the GPU path is ready for use without a separate GPU validation playbook
- that SSO is ready as a primary login path without a separate real-infrastructure validation
- that the current dashboard access model is enterprise-ready
- that the system is HA-ready or closes secret-manager, DLP, SIEM, and compliance requirements

## Related documents

- [PILOT_SCOPE_en.md](PILOT_SCOPE_en.md)
- [PILOT_LIMITATIONS_en.md](PILOT_LIMITATIONS_en.md)
- [PILOT_ACCEPTANCE_CHECKLIST_en.md](PILOT_ACCEPTANCE_CHECKLIST_en.md)
- [GPU_VALIDATION_PLAYBOOK_en.md](GPU_VALIDATION_PLAYBOOK_en.md)
- [PILOT_RUNBOOK_en.md](PILOT_RUNBOOK_en.md)

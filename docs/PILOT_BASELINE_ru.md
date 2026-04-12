# Базовая линия пилота

## Назначение

Этот документ сохраняет reference на более ранний pilot baseline package для Corporate AI Assistant. Он нужен для исторической traceability пилота и не должен читаться как текущий release-candidate baseline `v1.2.0`.

## Точная фиксация baseline

- branch: `main`
- exact historical baseline SHA: `33960581772787b162a0885bc2181f650f22a168`
- historical short SHA: `3396058`
- baseline type: historical documentation/package baseline для более раннего pilot package

## Что уже реализовано в текущем baseline

В текущем baseline уже реализованы и задокументированы:

- поддерживаемый deployment path: Linux VM + Docker Compose + `install.sh`
- Kerberos + LDAP-backed password login
- optional trusted reverse-proxy SSO path в runtime и docs
- обычный web chat
- file-chat через parser-stage path с `worker-parser` и shared staging
- read-only operator dashboard с `summary/live/history/events`
- Redis/PostgreSQL transitional conversation persistence baseline
- installer-driven `.env`, Kerberos, TLS и stack bootstrap
- safe uninstall и manifest-driven `factory-reset` uninstall path

Важная граница baseline:

- dashboard access model остаётся временным узким operator gate и не должен описываться как production-ready RBAC

## Что подтверждено на уровне репозитория

В репозитории уже есть согласованный code/docs baseline и зафиксированное repo-level evidence по ключевым зонам:

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

Это доказательство реализованного repository baseline, но не замена fresh install validation и не замена real infra validation.

## Что зафиксировано как подтверждение на уровне VM

По текущему source of truth:

- `docs/SUPPORTED_OS.md` фиксирует recorded clean installer validation point на Ubuntu 24.04 для revision `eba7ea9` внутри текущего release family
- supported installer targets остаются `Ubuntu 20.04+` и `Debian 11+`
- exact historical pilot HEAD `3396058` не является текущим release-candidate baseline `v1.2.0`

Иными словами:

- есть recorded validation evidence для release family
- этот SHA остаётся только историческим reference для pilot package
- fresh install re-validation exact current release-candidate HEAD перед финальным tag `v1.2.0` всё ещё остаётся отдельным шагом

## Что ещё требует отдельной валидации

Отдельно не доказано и не должно подразумеваться автоматически:

- GPU readiness на dedicated GPU host
- real-infra trusted reverse-proxy SSO на финальном FQDN/SPN/keytab path
- production-grade dashboard access model
- final authoritative ownership cutover conversation data на PostgreSQL без Redis fallback bridge
- HA, external secret manager, centralized SIEM/observability integrations

## Что именно должен доказать этот baseline в пилоте

Этот pilot baseline предназначен доказать следующее:

- exact baseline SHA можно развернуть по supported path без изменения runtime semantics
- CPU-first on-prem baseline даёт рабочий login, normal chat, file-chat и operator monitoring
- install, acceptance, runbook и handoff docs достаточны для controlled pilot execution
- ограничения baseline сформулированы честно и могут быть приняты до начала пилота

## Что этот baseline не доказывает

Этот baseline сам по себе не доказывает:

- что GPU path готов к использованию без отдельного GPU validation playbook
- что SSO готово как основной login path без отдельной real-infra validation
- что текущий dashboard access model является enterprise-ready
- что система является HA-ready или закрывает secret-manager, DLP, SIEM и compliance requirements

## Связанные документы

- [PILOT_SCOPE_ru.md](PILOT_SCOPE_ru.md)
- [PILOT_LIMITATIONS_ru.md](PILOT_LIMITATIONS_ru.md)
- [PILOT_ACCEPTANCE_CHECKLIST_ru.md](PILOT_ACCEPTANCE_CHECKLIST_ru.md)
- [GPU_VALIDATION_PLAYBOOK_ru.md](GPU_VALIDATION_PLAYBOOK_ru.md)
- [PILOT_RUNBOOK_ru.md](PILOT_RUNBOOK_ru.md)

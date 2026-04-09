# ai_agent_v1.1 — Corporate AI Assistant

[Русский — основной документ](README.ru.md) | [Documentation map](docs/INDEX.md) | [English summary](README.md)

Corporate AI Assistant `ai_agent_v1.1` — локальный корпоративный AI-ассистент для русскоязычной enterprise-среды. Продукт ориентирован на развёртывание внутри организации, где важны контролируемый Linux VM deployment, аутентификация через Active Directory и локальный inference без внешнего SaaS.

Этот репозиторий содержит релизную основу `v1.1.0` и последующие hardening/documentation updates, уже внесённые в текущую ветку. Для v1.1 supported deployment baseline сформулирован однозначно: Linux VM + Docker Compose + `install.sh`.

Legacy helper files могут оставаться в репозитории для совместимости и справки, но они не являются основным поддерживаемым путём.

## Кратко о текущем состоянии

- FastAPI backend с web UI и Jinja2 templates
- login через Kerberos + LDAP-backed password flow
- optional trusted reverse-proxy SSO path
- Redis-backed session, rate-limit и job state
- PostgreSQL-backed conversation persistence groundwork с dual-write/read-cutover flags
- Ollama как локальный inference runtime
- parser-based file-chat path с отдельным `worker-parser` и shared staging
- read-only operator dashboard с live telemetry, history и events
- русскоязычный набор operator docs с синхронизированными английскими версиями

## Поддерживаемый baseline развёртывания

- Ubuntu 20.04+ или Debian 11+
- 4 vCPU / 8 GB RAM minimum
- 8 vCPU / 16 GB RAM recommended
- Active Directory / Kerberos / LDAP доступны с хоста и из контейнеров
- поддерживаемый путь для v1.1: Linux VM + Docker Compose + `install.sh`
- baseline path — CPU-first deployment
- GPU profile остаётся optional и требует отдельно подготовленного хоста

## Границы текущей валидации

- текущая ветка отражает чистый code/docs baseline, но exact current HEAD всё ещё нужно отдельно перепроверить через fresh install перед pilot freeze
- GPU profile требует отдельной runtime validation на целевом GPU host
- trusted reverse-proxy SSO требует отдельной infra/runtime validation на реальном FQDN/SPN/keytab path

## Краткая сводка по baseline пилота

- pilot baseline candidate: `33960581772787b162a0885bc2181f650f22a168` (`3396058`) на `main`
- baseline уже включает supported Linux VM + Docker Compose + `install.sh`, password login, normal chat, file-chat, read-only operator dashboard и uninstall/factory-reset flow
- отдельно ещё не доказаны: fresh install re-validation exact current HEAD, GPU host validation и real-infra SSO validation
- цель пилота: доказать CPU-first baseline, operator handoff и честные ограничения, а не обещать HA, enterprise SSO или GPU readiness по умолчанию
- pilot package: [docs/PILOT_BASELINE_ru.md](docs/PILOT_BASELINE_ru.md), [docs/PILOT_SCOPE_ru.md](docs/PILOT_SCOPE_ru.md), [docs/PILOT_LIMITATIONS_ru.md](docs/PILOT_LIMITATIONS_ru.md), [docs/PILOT_ACCEPTANCE_CHECKLIST_ru.md](docs/PILOT_ACCEPTANCE_CHECKLIST_ru.md), [docs/GPU_VALIDATION_PLAYBOOK_ru.md](docs/GPU_VALIDATION_PLAYBOOK_ru.md), [docs/PILOT_RUNBOOK_ru.md](docs/PILOT_RUNBOOK_ru.md)

## Порядок чтения

1. [docs/INDEX.md](docs/INDEX.md) — карта документации и роли документов
2. [docs/PILOT_BASELINE_ru.md](docs/PILOT_BASELINE_ru.md) — кандидат в baseline пилота, границы доказанности и статус валидации
3. [docs/SUPPORTED_OS.md](docs/SUPPORTED_OS.md) — canonical matrix поддерживаемых ОС, validated и unsupported статусов
4. [QUICKSTART.md](QUICKSTART.md) — shortest path до первого запуска
5. [docs/INSTALL_ru.md](docs/INSTALL_ru.md) или [docs/INSTALL_en.md](docs/INSTALL_en.md) — полная установка и поведение installer
6. [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md) — production-specific deltas и требования к публикации сервиса
7. [docs/ADMIN_ru.md](docs/ADMIN_ru.md) / [docs/ADMIN_en.md](docs/ADMIN_en.md) — day-2 operations
8. [docs/SECURITY_ru.md](docs/SECURITY_ru.md) / [docs/SECURITY_en.md](docs/SECURITY_en.md) — product security baseline
9. [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md) — полная диагностика и recovery
10. [docs/ARCHITECTURE_ru.md](docs/ARCHITECTURE_ru.md) / [docs/ARCHITECTURE_en.md](docs/ARCHITECTURE_en.md) — реализованная архитектура

## Документация

- [docs/INDEX.md](docs/INDEX.md)
- [docs/PILOT_BASELINE_ru.md](docs/PILOT_BASELINE_ru.md)
- [docs/PILOT_SCOPE_ru.md](docs/PILOT_SCOPE_ru.md)
- [docs/PILOT_LIMITATIONS_ru.md](docs/PILOT_LIMITATIONS_ru.md)
- [docs/PILOT_ACCEPTANCE_CHECKLIST_ru.md](docs/PILOT_ACCEPTANCE_CHECKLIST_ru.md)
- [docs/GPU_VALIDATION_PLAYBOOK_ru.md](docs/GPU_VALIDATION_PLAYBOOK_ru.md)
- [docs/PILOT_RUNBOOK_ru.md](docs/PILOT_RUNBOOK_ru.md)
- [docs/SUPPORTED_OS.md](docs/SUPPORTED_OS.md)
- [QUICKSTART.md](QUICKSTART.md)
- [docs/INSTALL_ru.md](docs/INSTALL_ru.md)
- [docs/INSTALL_en.md](docs/INSTALL_en.md)
- [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md)
- [docs/ADMIN_ru.md](docs/ADMIN_ru.md)
- [docs/ADMIN_en.md](docs/ADMIN_en.md)
- [docs/SECURITY_ru.md](docs/SECURITY_ru.md)
- [docs/SECURITY_en.md](docs/SECURITY_en.md)
- [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md)
- [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- [docs/ARCHITECTURE_ru.md](docs/ARCHITECTURE_ru.md)
- [docs/ARCHITECTURE_en.md](docs/ARCHITECTURE_en.md)
- [CHANGELOG.md](CHANGELOG.md)
- [website/index.html](website/index.html) — статический сайт проекта и отдельная страница каталога моделей

## Ограничения текущего релиза

- Redis по умолчанию single-node
- self-signed TLS остаётся дефолтным installer path
- GPU deployment не считается baseline path
- dashboard access model остаётся временным operator gate и не является production-ready RBAC
- расширенная observability и HA-профили не входят в этот release snapshot
- качество и latency зависят от выбранной модели Ollama и профиля железа
## Лицензия

Проект распространяется по лицензии MIT. См. [LICENSE](LICENSE).

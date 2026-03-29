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
- Ollama как локальный inference runtime
- русскоязычный набор operator docs с синхронизированными английскими версиями

## Поддерживаемый baseline развёртывания

- Ubuntu 20.04+ или Debian 11+
- 4 vCPU / 8 GB RAM minimum
- 8 vCPU / 16 GB RAM recommended
- Active Directory / Kerberos / LDAP доступны с хоста и из контейнеров
- поддерживаемый путь для v1.1: Linux VM + Docker Compose + `install.sh`
- baseline path — CPU-first deployment
- GPU profile остаётся optional и требует отдельно подготовленного хоста

## Порядок чтения

1. [docs/INDEX.md](docs/INDEX.md) — карта документации и роли документов
2. [QUICKSTART.md](QUICKSTART.md) — shortest path до первого запуска
3. [docs/INSTALL_ru.md](docs/INSTALL_ru.md) или [docs/INSTALL_en.md](docs/INSTALL_en.md) — полная установка и поведение installer
4. [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md) — production-specific deltas и требования к публикации сервиса
5. [docs/ADMIN_ru.md](docs/ADMIN_ru.md) / [docs/ADMIN_en.md](docs/ADMIN_en.md) — day-2 operations
6. [docs/SECURITY_ru.md](docs/SECURITY_ru.md) / [docs/SECURITY_en.md](docs/SECURITY_en.md) — product security baseline
7. [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md) — полная диагностика и recovery
8. [docs/ARCHITECTURE_ru.md](docs/ARCHITECTURE_ru.md) / [docs/ARCHITECTURE_en.md](docs/ARCHITECTURE_en.md) — реализованная архитектура

## Документация

- [docs/INDEX.md](docs/INDEX.md)
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

## Ограничения текущего релиза

- Redis по умолчанию single-node
- self-signed TLS остаётся дефолтным installer path
- GPU deployment не считается baseline path
- расширенная observability и HA-профили не входят в этот release snapshot
- качество и latency зависят от выбранной модели Ollama и профиля железа
## Лицензия

Проект распространяется по лицензии MIT. См. [LICENSE](LICENSE).

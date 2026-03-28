# ai_agent_v1.1 — Corporate AI Assistant

[Русский — основной документ](README.ru.md) | [English summary](README.md)

Corporate AI Assistant `ai_agent_v1.1` — локальный корпоративный AI-ассистент для русскоязычной enterprise-среды. Продукт ориентирован на развёртывание внутри организации, где важны контролируемый Linux VM deployment, аутентификация через Active Directory и локальный inference без внешнего SaaS.

Этот workspace подготовлен как clean release snapshot на базе validated code baseline `bab04bf`. Основной поддерживаемый сценарий — Linux VM + Docker Compose + Nginx + Redis + Ollama + Kerberos/LDAP authentication.

## Что реально входит в релизную основу

- FastAPI backend с web UI и Jinja2 templates
- login через Kerberos + LDAP-backed password flow
- optional trusted reverse-proxy SSO path
- Redis-backed session, rate-limit и job state
- Ollama как локальный inference runtime
- Docker Compose deployment с Nginx TLS ingress
- installer `install.sh` для чистой Linux VM
- базовый набор operator docs на русском и английском

## Что уже подтверждено в релизной основе

В validated baseline уже входят исправления, которые были реально проверены в runtime:

- корректная генерация installer-managed `docker-compose.override.yml` без duplicate AD host aliases
- корректный `TemplateResponse(request, ...)` для `/login`
- корректный LDAP/GSSAPI runtime lookup с отключением SASL canonicalization через `ldapsearch -N`
- корректный `TemplateResponse(request, ...)` для `/chat`

Этот README не утверждает новую clean-VM validation именно для будущего публичного репозитория. Такая проверка выполняется отдельной фазой release-процесса.

## Поддерживаемый сценарий развёртывания

- Ubuntu 20.04+ или Debian 11+
- 4 vCPU / 8 GB RAM minimum
- 8 vCPU / 16 GB RAM recommended
- Active Directory / Kerberos / LDAP доступны с хоста и из контейнеров
- основной путь — CPU-first deployment
- GPU profile остаётся optional и требует отдельно подготовленного хоста

## Быстрый старт

После публикации релизного репозитория замените `<repo-url>` на фактический URL:

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
chmod +x install.sh
./install.sh
```

Затем проверьте:

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

## Что важно подготовить заранее

- DNS-домен AD
- hostname или FQDN LDAP-сервера
- hostname или FQDN Kerberos KDC
- base DN
- тестовую AD-учётную запись для smoke login, если нужен auth-check
- при необходимости — AD IP override для контейнеров
- если планируется SSO:
  - trusted HTTPS FQDN
  - `HTTP/<fqdn>@REALM` SPN
  - service keytab
  - доверенный TLS certificate

## Аутентификация и вход

По умолчанию основной пользовательский путь — обычный login form:

- пользователь вводит AD credentials на `/login`
- backend получает Kerberos ticket
- directory attributes и model access groups резолвятся через LDAP / GSSAPI
- access / refresh / csrf cookies выставляются приложением
- при успешном входе пользователь попадает на `/chat`

SSO path существует, но:

- выключен по умолчанию
- требует trusted reverse proxy
- требует service keytab
- требует trusted certificate на реальном FQDN
- должен валидироваться отдельно от password-login

## LDAP / Kerberos note

Для рабочего LDAP/GSSAPI path важны hostname и SPN consistency.

- не используйте raw IP в `LDAP_SERVER` или `KERBEROS_KDC`
- short hostname может быть валиден, если именно он соответствует зарегистрированному SPN
- FQDN тоже допустим, но только если AD/SPN/DNS настроены согласованно
- lab-значения вроде `srv-ad`, `srv-ad.corp.local` или `10.10.10.10` должны рассматриваться только как примеры, а не как универсальные константы релиза

## TLS и сертификаты

Installer по умолчанию генерирует self-signed TLS material в `deploy/certs/`.

Это допустимо для:

- first-run smoke validation
- внутренних пилотов
- изолированных лабораторных стендов

Для production-публикации сервиса рекомендуется заменить self-signed material на корпоративный или публично доверенный certificate chain.

## Модели

Репозиторий не хранит веса моделей в git и не включает их в Docker image.

Примеры проверок:

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
```

Если в runtime нет ни одной модели, stack может подняться, но chat path не будет готов к работе.

## Что не хранится в release repo

В clean release tree не должны попадать:

- `.env`
- installer logs и `.install/`
- `docker-compose.override.yml`
- generated TLS material
- keytab files
- runtime cookies
- локальные smoke-артефакты
- модели и Ollama runtime data

## Документация

Основные документы:

- [README.md](README.md) — краткая английская версия
- [docs/INSTALL_ru.md](docs/INSTALL_ru.md)
- [docs/INSTALL_en.md](docs/INSTALL_en.md)
- [docs/ARCHITECTURE_ru.md](docs/ARCHITECTURE_ru.md)
- [docs/ARCHITECTURE_en.md](docs/ARCHITECTURE_en.md)
- [docs/SECURITY_ru.md](docs/SECURITY_ru.md)
- [docs/SECURITY_en.md](docs/SECURITY_en.md)
- [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md)
- [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md)
- [CHANGELOG.md](CHANGELOG.md)

Полезный runtime helper:

- `AUTH_CHECK_PASSWORD='***' ./diagnose_auth_runtime.sh <username>`

## Ограничения текущего релиза

- Redis по умолчанию single-node
- self-signed TLS остаётся дефолтным installer path
- GPU deployment не считается baseline path
- расширенная observability и HA-профили не входят в этот release snapshot
- качество и latency зависят от выбранной модели Ollama и профиля железа

## Лицензия

Проект распространяется по лицензии MIT. См. [LICENSE](LICENSE).

# Базовый security baseline

## Область действия

Этот документ описывает текущий security baseline Corporate AI Assistant в том виде, в котором он реально реализован в репозитории сейчас. Это не заявление о полной enterprise security coverage.

Текущую security posture лучше воспринимать так:

- baseline для внутреннего deployment
- пригодно для пилота при аккуратной operator hardening
- не заменяет организационные security controls

## Предположения по deployment

Репозиторий рассчитан на внутреннее развёртывание за управляемыми сетью и инфраструктурой средствами защиты. От оператора ожидается:

- доверенное размещение в сети
- корректный host hardening
- принятые в организации практики работы с секретами
- замена сертификатов перед production use

## Authentication и session model

### Что реализовано

- login flow на базе Kerberos и LDAP
- JWT-based access и refresh tokens
- cookies для переноса токенов
- logout revocation через Redis-backed token state
- rate limiting для логина
- fail-closed поведение при недоступности auth backend
- proxy-terminated AD SSO session issuance через выделенный trusted reverse-proxy path
- refresh-token rotation на `/api/refresh`
- явные session metadata в token claims:
  - `auth_source=password`
  - `auth_source=sso`
  - `auth_time`
  - `directory_checked_at`
  - `identity_version`
  - `canonical_principal`

### Session и CSRF baseline

Сейчас приложение включает:

- HTTP cookie-based session transport
- CSRF token validation для modifying requests
- cookie configuration через environment variables
- узкий bearer-only CSRF bypass для non-cookie API clients
- явный reject зарезервированных proxy-auth headers, пока trusted proxy SSO mode выключен
- зарезервированные proxy-auth headers принимаются только на выделенном SSO entry path (`/auth/sso/login`) и только от доверенного proxy source
- основной FastAPI app по-прежнему не принимает raw `Authorization: Negotiate ...` как auth path
- startup validation environment secrets и proxy-boundary настроек:
  - placeholder passwords в `REDIS_URL` и `PERSISTENT_DB_URL` отклоняются
  - для non-local Redis/PostgreSQL требуется явный пароль
  - `TRUSTED_PROXY_SOURCE_CIDRS` должен быть валиден и обязателен при включённом trusted-proxy SSO
- Uvicorn proxy-header trust больше не использует wildcard allowlist; он задаётся через `FORWARDED_ALLOW_IPS`

### Текущий статус SSO

В репозитории теперь есть реальный SSO path, но только при жёстком trusted-proxy contract:

- password login остаётся рабочим fallback
- SSO по умолчанию выключен
- SSO работает только если одновременно включены `SSO_ENABLED=true` и `TRUSTED_AUTH_PROXY_ENABLED=true`
- Uvicorn должен доверять forwarded headers только от reverse-proxy hop; это настраивается через `FORWARDED_ALLOW_IPS`
- `TRUSTED_PROXY_SOURCE_CIDRS` должен явно перечислять source addresses/CIDR того reverse proxy, который делает hop до `app`
- browser-facing Kerberos/SPNEGO negotiation завершается до основного app
- основной app принимает только proxy-validated identity headers и только на выделенном SSO entry path
- на обычных route'ах app не принимает произвольные identity headers
- model access для SSO session идёт через ту же цепочку `.env` group mapping + explicit model catalog, что и для password session

### Текущее ограничение

- refresh всё ещё сохраняет последний directory-derived identity snapshot и не делает новую AD-проверку на каждом refresh
- SSO требует реальных infra prerequisites:
  - trusted HTTPS FQDN
  - валидный `HTTP/<fqdn>@REALM` SPN
  - service keytab, смонтированный в `deploy/sso/`
  - корректный `FORWARDED_ALLOW_IPS`, совпадающий с source IP/CIDR reverse proxy hop до `app`
  - корректный `TRUSTED_PROXY_SOURCE_CIDRS`, совпадающий с адресами reverse proxy на hop до `app`
  - domain-joined clients и корректную browser trust-zone configuration
- logout в app очищает только локальную application session и не означает logout из Windows, Kerberos или browser SPNEGO state
- model access control теперь использует явный folder-based policy catalog в `model_policies/`, но это всё ещё простая категорийная policy, а не полноценный enterprise RBAC
- имена AD-групп для категорий `coding` и `admin` больше не зашиты в runtime-коде; они задаются через `.env` как `MODEL_ACCESS_CODING_GROUPS` и `MODEL_ACCESS_ADMIN_GROUPS`
- пользователь по-прежнему сам выбирает модель, но только из policy-approved видимого набора
- `general` даётся всем аутентифицированным пользователям, а `coding` и `admin` зависят от exact group match из `.env`
- policy files содержат только metadata и не являются model weights; сами по себе они не включают SSO

### Важное operational note

Kerberos/LDAP path зависит от согласованности hostname и SPN. Неправильная DNS/SPN-конфигурация может ломать authentication даже при валидных credentials.

## Transport security

### Что реализовано

- Nginx как HTTPS ingress
- поддержка TLS certificates в deployment layout
- поддержка выделенного `sso-proxy` helper'а для trusted reverse-proxy Kerberos/SPNEGO validation

### Текущее ограничение

Installer по умолчанию генерирует self-signed certificates. Для внутреннего smoke testing и early pilot это допустимо, но для production posture это не рекомендуемый вариант. Kerberos/SPNEGO SSO нужно использовать с trusted certificate на реальном FQDN.

## Redis и runtime boundary

### Что реализовано

- Redis предполагается оставлять только во внутренней Compose network
- публичная точка входа — Nginx, а не Redis и не FastAPI container напрямую
- runtime health и queue state не публикуются как внешняя database API

### Текущее ограничение

- Redis по умолчанию single-node
- HA Redis profile пока не поставляется

## Dashboard telemetry boundary

### Что реализовано

- read-only operator dashboard под `/admin/dashboard`
- dashboard API surfaces:
  - `/api/admin/dashboard/summary`
  - `/api/admin/dashboard/live`
  - `/api/admin/dashboard/history`
  - `/api/admin/dashboard/events`
- honest no-data / unavailable semantics для telemetry, GPU и history
- dashboard не публикует fake metrics и не подменяет missing telemetry нулём

### Текущее ограничение

- текущая модель доступа к dashboard остаётся узким env-driven operator gate (`ADMIN_DASHBOARD_USERS`), а не production-ready RBAC
- dashboard payloads раскрывают operational telemetry, history и event context, поэтому этот surface нужно считать operator-only
- если SSO планируется использовать и для dashboard access, это всё равно требует отдельной real-infra validation

## Upload и file security baseline

### Что реализовано

Текущий upload path включает:

- allowlist по file extensions
- allowlist по MIME/content-type mapping
- совместимый fallback для пустого или generic content-type
- safe filename normalization
- file size limits
- file count limits
- временный staging вместо durable attachment store
- cleanup временных upload artifacts

Поддерживаемые upload types сейчас:

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### От чего этот baseline реально защищает

- от очевидных unsupported uploads
- от очевидных extension-only abuse
- от типовых content-type mismatch cases
- от path traversal через filename

### Что не реализовано

- antivirus scanning
- sandbox execution
- file signature sniffing с глубокой type verification
- DLP или content classification
- durable attachment access-control model

## Baseline для prompt и model safety

### Что реализовано

- prompt injection filtering для прямых пользовательских prompt'ов
- context governance для history, document context и total prompt size
- grounded document prompts для file-chat
- anti-hallucination framing для document-based answers

### Текущее ограничение

- это снижение рисков на уровне prompt layer, а не полноценная model safety system
- внешний policy engine не интегрирован

## Baseline логирования и утечки данных

### Что реализовано

- structured operational logs
- логирование upload rejection без содержимого файла
- timing-логи для parse/queue/inference/terminal stages
- отсутствие raw document preview в текущем file-chat observability path

### Что всё равно требует аккуратности

- логи всё ещё могут содержать usernames, model identifiers и error metadata
- Redis содержит live job state и chat history

## Известные security gaps

В этом репозитории пока не полностью реализованы:

- интеграция с внешним secret manager
- HA control plane
- централизованная SIEM forwarding
- antivirus или sandbox-based file scanning
- fine-grained admin controls
- production-ready dashboard role/claim model
- packaged compliance controls
- multi-layer content classification или DLP

## Рекомендации для pilot use

Перед пилотом или внутренним rollout рекомендуется:

- заменить self-signed certificates на trusted TLS material
- ротировать `SECRET_KEY` и `REDIS_PASSWORD`
- ограничить host access и management access по внутренней политике
- проверить AD hostname/SPN behavior через smoke account
- проверить HTTP service principal и keytab до включения SSO
- отдельно проверить SSO в domain-joined browser и только потом полагаться на него как на primary path
- проверить наличие хотя бы одной рабочей Ollama model
- проверить file-chat на разрешённых типах файлов
- если планируется GPU, отдельно валидировать host GPU container support до включения профиля

## Что остаётся planned или operator-owned

- централизованные metrics и alerting
- HA Redis
- enterprise certificate lifecycle automation
- advanced malware scanning
- более широкие admin policy tooling

## Связанные документы

- [README.md](../README.md)
- [Install Guide](INSTALL_ru.md)
- [Архитектура](ARCHITECTURE_ru.md)
- [Администрирование и эксплуатация](ADMIN_ru.md)
- [Troubleshooting](TROUBLESHOOTING_ru.md)

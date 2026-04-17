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

## Supply-chain baseline

### Что реализовано

- Docker build теперь опирается на pinned [requirements.lock](../requirements.lock), а не только на loose `requirements.txt`
- `Dockerfile` использует pinned Python base image digest
- Compose external images для `redis`, `postgres`, `ollama` и `nginx` теперь имеют pinned baseline references вместо `latest`

### Текущее ограничение

- это minimal reproducibility baseline, а не полный software supply-chain framework
- host apt repositories, Docker Engine packages и внешние installer downloads всё ещё зависят от operator-controlled infrastructure
- digest/lock refresh остаётся осознанной operator/release задачей и требует повторной валидации

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

### Local break-glass admin

Для аварийного operator access runtime теперь поддерживает отдельный local break-glass admin path, но только как controlled fallback для dashboard surface:

- local admin disabled by default через `LOCAL_ADMIN_ENABLED=false`
- username по умолчанию: `LOCAL_ADMIN_USERNAME=admin_ai`
- в `.env` хранится только `LOCAL_ADMIN_PASSWORD_HASH`; plaintext password не используется
- installer-managed `.env` хранит `LOCAL_ADMIN_PASSWORD_HASH` в compose-safe escaped `$$` виде, чтобы Docker Compose не искажал hash на transport boundary
- если installer не получает явный пароль, он генерирует one-time bootstrap secret и сохраняет его plaintext только в root-only host file с `0600`
- пока `LOCAL_ADMIN_FORCE_ROTATE=true` и `LOCAL_ADMIN_BOOTSTRAP_REQUIRED=true`, первый вход local admin допускается только к forced password rotation flow
- до завершения rotation local admin session не получает доступ к `/admin/dashboard` и `/api/admin/dashboard/*`
- после forced rotation аутентифицированная local-admin session может использовать обычный `GET/POST /admin/local/change-password`
- normal change-password flow доступен только для валидной local-admin session без pending rotation; anonymous requests и обычные AD sessions получают deny
- после успешной смены пароля bootstrap secret инвалидируется, текущая local-admin session разлогинивается, а старая session revision отклоняется fail-closed
- local admin session использует отдельные cookies и отдельный auth source, поэтому не подменяет обычный chat/session flow
- login attempts, logout, forced rotation и обычная смена пароля логируются без утечки plaintext secret или password material
- `ADMIN_DASHBOARD_USERS` остаётся отдельным ordinary-operator gate и не заменяется local-admin fallback path

### Standalone/test chat user

Для isolated demo/standalone validation runtime теперь поддерживает отдельного standalone/test chat user на обычном `POST /login`, но только как явно выключаемый test-only path:

- standalone/test chat user disabled by default через `STANDALONE_CHAT_AUTH_ENABLED=false`
- username по умолчанию: `STANDALONE_CHAT_USERNAME=demo_ai`
- этот user отделён от local break-glass dashboard admin и не расширяет dashboard access
- в `.env` хранится только `STANDALONE_CHAT_PASSWORD_HASH`; plaintext password не используется
- installer-managed `.env` хранит `STANDALONE_CHAT_PASSWORD_HASH` в compose-safe escaped `$$` виде, чтобы Docker Compose не искажал hash на transport boundary
- если installer в `standalone_gpu_lab` не получает явный пароль, он может сгенерировать one-time bootstrap secret и сохранить plaintext только в root-only host file с `0600`
- bootstrap/rotation state отражается через `STANDALONE_CHAT_FORCE_ROTATE` и `STANDALONE_CHAT_BOOTSTRAP_REQUIRED`
- если `STANDALONE_CHAT_AUTH_ENABLED=true` и введённый username совпадает с `STANDALONE_CHAT_USERNAME`, runtime делает только локальную hash-only password verification для этого одного пользователя
- неверный пароль даёт `401` и не переводит login в anonymous/open mode
- все остальные usernames продолжают идти в обычный Kerberos/AD flow
- этот standalone/test chat user предназначен только для обычного chat UI и demo/testing, а не как замена production AD auth

### Standalone GPU Lab mode

Для isolated GPU validation runtime поддерживает explicit profile `standalone_gpu_lab`, но его рекомендуемый auth path теперь остаётся закрытым по умолчанию:

- baseline по умолчанию остаётся enterprise: `INSTALL_PROFILE=enterprise`, `AUTH_MODE=ad`
- в поддерживаемом `standalone_gpu_lab` installer по-прежнему не требует AD domain, LDAP server и Kerberos KDC и пропускает Kerberos/LDAP smoke test
- поддерживаемый test-login path для этого профиля теперь строится вокруг `STANDALONE_CHAT_*`, а не вокруг synthetic open login
- ordinary `/login` форма остаётся той же; standalone/test chat user работает только если оператор явно включил его и задал hash-only / bootstrap-secret credentials
- legacy `AUTH_MODE=lab_open` contract остаётся только для explicit backward compatibility и больше не является рекомендуемым installer path
- этот профиль и любой standalone/test chat user нельзя публиковать в production или в открытый Интернет без жёсткой сетевой изоляции

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

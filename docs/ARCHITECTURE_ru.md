# Архитектура

## Область действия

Этот документ описывает текущую реализованную архитектуру Corporate AI Assistant. Он опирается только на то, что реально есть в репозитории сейчас, и отдельно отмечает planned-части.

## Общий обзор системы

Corporate AI Assistant разворачивается через Docker Compose и состоит из:

- `nginx` для HTTPS ingress
- `app` как FastAPI web/API plane
- `sso-proxy` для внутренней Kerberos/SPNEGO validation за reverse proxy
- `scheduler` для admission control и stale-job recovery
- `worker-chat`, `worker-siem` и `worker-batch` для выполнения workloads
- optional `worker-gpu` для GPU-targeted chat execution
- `redis` для chat history, rate limiting, queues, heartbeats, leases, job state и event streams
- `ollama` для локального model inference

Внешние зависимости:

- Active Directory / Kerberos / LDAP
- браузерные клиенты по HTTPS

## Ответственность компонентов

### `nginx`

- завершает TLS
- публикует порты `80` и `443`
- проксирует обычный трафик в FastAPI app
- обрабатывает выделенный `/auth/sso/login` через `auth_request`
- очищает зарезервированные identity headers на обычном application path

### `sso-proxy`

`sso-proxy` — это внутренний helper-сервис только для trusted reverse-proxy SSO:

- получает `Authorization: Negotiate ...` от Nginx во внутреннем auth subrequest
- валидирует Kerberos/SPNEGO через настроенный HTTP service keytab
- резолвит user identity и AD groups через уже существующую Kerberos/LDAP integration
- возвращает нормализованные identity headers обратно в Nginx

Этот сервис не публикуется напрямую браузерным клиентам.

### `app`

FastAPI-приложение отвечает за:

- login и lifecycle сессий
- интеграцию с Kerberos/LDAP authentication
- CSRF enforcement
- выпуск password-based session с rotated refresh tokens
- выпуск SSO-based session из proxy-validated identity на выделенном `/auth/sso/login`
- canonical identity normalization для `DOMAIN\\user`, `user@REALM` и plain username
- model selection и runtime model resolution через явный folder-based policy catalog (`model_policies/`)
- приём обычных chat requests
- staging upload, parser jobs и document processing
- health endpoints
- SSE event streaming в браузер

Для file-chat baseline fresh install использует parser-stage path: `app` выполняет валидацию и controlled staging, ставит parser root job в очередь, `worker-parser` готовит grounded document artifacts, а downstream worker выполняет inference. Legacy app-side parsing path остаётся только fallback-веткой при выключенном parser public cutover.

Текущая parser-stage архитектура и её design rationale описаны в [PARSER_STAGE_DESIGN.md](PARSER_STAGE_DESIGN.md).

Основной app не выполняет raw Kerberos/SPNEGO negotiation напрямую. Вместо этого он принимает trusted identity headers только на выделенном SSO entry path и только при включённом trusted proxy mode. Password login остаётся доступным fallback auth source.

Policy catalog не является директорией хранения моделей. Он определяет только то, какие exact model keys входят во внутренние категории проекта. Доступ к категориям вычисляется отдельно через `.env` group mapping: authenticated users получают `general`, а `coding` и `admin` открываются только при exact AD group match из `MODEL_ACCESS_CODING_GROUPS` и `MODEL_ACCESS_ADMIN_GROUPS`. Пользователь по-прежнему вручную выбирает модель из разрешённого набора, который приходит через `/api/models`.

### `scheduler`

Scheduler — это отдельный runtime process, который:

- поддерживает свежий scheduler heartbeat
- оценивает workload capacity
- перемещает jobs из pending queues в dispatch queues
- при необходимости requeue'ит stale jobs

Это часть control plane, а не web/API plane.

### `worker-chat`, `worker-siem`, `worker-batch`

Worker'ы:

- публикуют worker heartbeats
- claim'ят jobs из dispatch queues
- проверяют совместимость `target_kind`
- собирают model messages из history и prompt
- вызывают Ollama
- публикуют job events и terminal status

Сейчас в репозитории используется одна worker-реализация, которая конфигурируется через environment variables под разные workloads.

### `worker-parser`

`worker-parser` — это выделенный parser pool для root file-chat jobs. Он:

- читает raw uploads из shared parser staging
- выполняет TXT/DOCX/PDF/image extraction
- применяет parser-side limits и budgets
- пишет parser-stage observability
- ставит downstream LLM child job в очередь
- очищает raw staged files, когда они больше не нужны

### `worker-gpu`

`worker-gpu` — optional Compose profile. Он предназначен для обработки `target_kind=gpu` chat jobs, когда:

- включён профиль `gpu`
- хост умеет запускать GPU-enabled containers
- включён GPU-targeted routing

Если GPU routing запрошен, но активного GPU worker нет, текущая реализация делает fallback на CPU.

### `redis`

Redis сейчас выполняет роль control plane и lightweight storage layer. Он используется для:

- chat history
- rate limiting
- состояния login/logout tokens
- job payloads и job status
- queue state
- dispatch и processing queues
- scheduler и worker heartbeats
- event streams

### `ollama`

Ollama — локальный inference runtime. Приложение ожидает, что в нём доступна хотя бы одна модель.

## Request paths

### Обычный chat path

1. браузер отправляет chat request в `app`
2. app проверяет auth, CSRF и rate limits
3. chat history загружается из Redis и ограничивается history governance
4. job ставится в очередь через LLM gateway
5. scheduler допускает job на target
6. worker claim'ит job и выполняет inference через Ollama
7. job events стримятся обратно в браузер
8. terminal state сохраняется в Redis, а ответ assistant добавляется в chat history

### SSO login path

1. пользователь открывает login page и явно выбирает SSO entry path
2. `nginx` выполняет внутренний auth subrequest в `sso-proxy`
3. `sso-proxy` валидирует Kerberos/SPNEGO negotiation и резолвит AD-backed identity
4. `nginx` передаёт в `app` только валидированные internal identity headers
5. `app` нормализует identity через тот же session contract, который используется для password login
6. `app` выпускает обычные access/refresh cookies с `auth_source=sso`
7. дальнейшие `/api/models`, `/api/switch-model`, chat и file-chat запросы используют уже обычный cookie/session flow

### File-chat path

1. браузер отправляет файлы и пользовательский запрос в `app`
2. app валидирует число файлов, размер файла, суммарный размер, extension и content-type
3. если включён parser public cutover, app пишет uploads в shared parser staging и ставит parser root job в очередь
4. `worker-parser` извлекает document text из поддерживаемых типов, применяет parser-side limits, trims document context и ставит downstream LLM child job
5. обычный worker выполняет grounded inference через стандартный model path
6. root/child terminal state зеркалируется обратно в browser-facing file-chat contract
7. raw staged artifacts очищаются по правилам parser lifecycle

Legacy fallback:

- при выключенном parser public cutover app сохраняет старый request-local staging/parsing path
- non-file chat никогда не использует parser path

Важные свойства:

- отдельной RAG-подсистемы нет
- отдельной document database нет
- извлечённый document text используется внутри текущего job lifecycle

## Поддерживаемые типы файлов

Текущий file parsing path поддерживает:

- `.txt`
- `.pdf`
- `.docx`
- `.png`
- `.jpg`
- `.jpeg`

PDF extraction использует parser chain, уже присутствующий в runtime приложения. Для image-файлов используется OCR path, собранный в container image.

## Модель данных и хранения

### Chat history

Chat history сейчас хранится в Redis через `AsyncChatStore`.

Текущие свойства:

- bounded history retention
- отдельной SQL database нет
- long-term archival backend в репозитории не реализован

### Job state

Job state хранится в Redis и включает:

- статус `pending / admitted / running / completed / failed / cancelled`
- target assignment
- lease и heartbeat-related metadata
- event stream entries, которые читают SSE consumers

### Uploaded files

Загруженные файлы staging'ятся временно для parsing. Parser path использует shared staging root, смонтированный в `app` и `worker-parser`; durable attachment store в репозитории не реализован.

## Context governance

В текущей реализации есть prompt-size governance:

- history ограничивается отдельно
- document context ограничивается отдельно
- final prompt size ограничивается отдельно

Цель — не допустить неконтролируемого роста prompt при максимальном сохранении user intent и document labels.

## CPU/GPU routing readiness

В репозитории есть базовый CPU/GPU routing layer:

- режим по умолчанию — CPU
- `GPU_ENABLED=true` запрашивает GPU routing
- worker'ы публикуют свой `target_kind`
- jobs несут `target_kind`
- если GPU worker недоступен, gateway понижает job до CPU

Текущие ограничения:

- auto-detect GPU capability для routing decisions не реализован
- успешный GPU path зависит от того, может ли хост реально запустить GPU-enabled containers

## Observability baseline

Сейчас в репозитории есть baseline observability через:

- health endpoints
- structured logs приложения
- structured logs worker'ов
- queue и terminal job logs

Текущие примеры:

- timing приёма upload/file request
- parse timing
- queue wait timing
- inference timing
- total job timing
- `file_count` и `doc_chars`
- routing target
- нормализованный `error_type`

Полноценный внешний metrics stack в репозитории не поставляется.

## Реализовано и planned

### Реализовано

- Docker Compose deployment
- AD/Kerberos/LDAP authentication path
- proxy-terminated AD SSO с password fallback
- queue/scheduler/worker control plane
- обычный SSE chat
- async file chat через parser root jobs и downstream queue/worker inference
- PDF/text/docx/image document extraction
- выделенный `worker-parser` и shared parser staging
- file-processing limits, budgets и controlled failures на malformed/heavy files
- CPU/GPU routing readiness с CPU fallback
- Redis-backed chat history и job state
- baseline upload validation и structured observability logs

### Planned или пока не реализовано

- выделенная persistent database для chat history
- HA Redis / Sentinel profile
- packaged external monitoring stack
- antivirus или sandbox-based file scanning
- standalone RAG subsystem
- Kubernetes deployment artifacts

## Связанные документы

- [Install Guide](INSTALL_ru.md)
- [Администрирование и эксплуатация](ADMIN_ru.md)
- [Troubleshooting](TROUBLESHOOTING_ru.md)
- [Базовый security baseline](SECURITY_ru.md)
- [README.md](../README.md)

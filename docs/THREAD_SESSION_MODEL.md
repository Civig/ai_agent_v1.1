# Server-side Thread And Session Model

Этот документ фиксирует целевую server-side модель `user / session / thread / message` для следующего implementation шага.

Статус документа:

- это design source of truth для шага `4.1`
- это не storage implementation plan по таблицам или Redis key layout
- это не меняет текущий runtime behavior само по себе

## 1. Текущее состояние

Сейчас в репозитории уже есть server-side authentication/session слой, per-thread history storage и backend truth для thread bootstrap, но полноценная session/archive platform ещё не завершена.

Что реально есть сейчас:

- identity определяется через cookie-based JWT session и normalised `username`
- backend хранит chat history в `AsyncChatStore` по primary key `chat:{username}:{thread_id}`
- backend ведёт per-user thread registry и умеет `list_threads()` / `create_thread()`
- обычный chat и file-chat уже читают и пишут history с учётом `thread_id`
- file-chat и parser path используют тот же thread-aware history contract
- cancel и observability тоже завязаны на `job_id` и `username`

Что реально делает frontend:

- `ThreadStore` bootstrap'ится из backend truth, а не из локального synthetic thread list
- `activeThreadId` живёт в browser state как текущий выбранный thread, но список диалогов и messages поднимается с backend
- `new chat` создаёт реальный server-side thread через `POST /api/threads`
- reload страницы поднимает backend thread list и history выбранного thread через `/chat`
- `GET /api/threads/{thread_id}/messages` используется для server-backed thread switching
- `POST /api/chat/clear` уже работает thread-aware и очищает только выбранный `thread_id`

Итог current state:

- server-side session есть
- server-side per-thread history есть
- server-side thread list / thread bootstrap truth уже есть
- frontend больше не является primary source of truth для thread list
- session-scoped active-thread pointer, archive и restore как platform capabilities ещё не реализованы

## 2. Главные ограничения текущей модели

- `username` всё ещё участвует в storage namespace и ownership, хотя primary history key уже thread-aware
- нет отдельной session-scoped server-side сущности для `active_thread_id`
- active thread после reload определяется через backend bootstrap/query flow, а не через отдельный persisted session pointer
- archive/restore отсутствуют как серверные операции
- новый браузерный session того же пользователя не имеет собственного active-thread pointer
- file-chat и parser path уже привязаны к конкретному durable `thread_id`, но не к полной session/thread platform

## 3. Целевая модель

Целевая модель должна сохранить текущий validated chat/file-chat runtime, но сделать backend authoritative source of truth для thread state.

Базовые принципы:

- `username` остаётся login identity, но перестаёт быть primary history key
- `user_id` становится внутренним стабильным идентификатором пользователя
- `session_id` становится идентификатором browser/app session
- `thread_id` становится идентификатором server-side диалога
- `message_id` становится идентификатором server-side сообщения
- `active thread` становится session-scoped server-side pointer, а не browser-only state
- archive/restore становятся server-side операциями над thread lifecycle

## 4. Целевые сущности

### 4.1 User

Минимальные поля:

- `user_id`
- `username`
- `canonical_principal`
- `display_name`
- `email`
- `auth_source`
- `created_at`
- `updated_at`

Семантика:

- `user_id` — внутренний opaque identifier
- `username` — нормализованный login name, который остаётся совместимым с текущим auth contract
- ownership всех thread/message records привязывается к `user_id`

### 4.2 Session

Минимальные поля:

- `session_id`
- `user_id`
- `auth_source`
- `created_at`
- `last_seen_at`
- `expires_at`
- `revoked_at`
- `active_thread_id`

Семантика:

- session представляет один browser/app login context
- token refresh сохраняет тот же `session_id`
- logout завершает session, но не удаляет threads пользователя
- `active_thread_id` принадлежит именно session, а не пользователю глобально

### 4.3 Thread

Минимальные поля:

- `thread_id`
- `user_id`
- `title`
- `state`
- `created_at`
- `updated_at`
- `archived_at`
- `last_message_at`

Допустимые состояния:

- `active`
- `inactive`
- `archived`

Семантика:

- `active` и `inactive` определяются относительно session binding
- один и тот же thread может быть active только для одной конкретной session в данный момент
- у пользователя может быть много inactive threads
- `archived` исключает thread из обычного append path до restore

### 4.4 Message

Минимальные поля:

- `message_id`
- `thread_id`
- `user_id`
- `role`
- `content`
- `created_at`
- `state`
- `source_message_id`
- `job_id`
- `attachments`

Семантика:

- `attachments` содержат только metadata, не binary payload
- `state` нужен для связки с текущим UI contract: `pending / streaming / done / cancelled / error`
- durable storage обязана фиксировать terminal result; streaming tokens могут оставаться transient transport detail

### 4.5 Async Job Linkage

Новый job storage слой в 4.1 не проектируется, но будущая реализация должна уметь связывать async jobs с thread model через metadata:

- `user_id`
- `session_id`
- `thread_id`
- `message_id` или `source_message_id`
- `job_id`
- для parser path дополнительно: `root_job_id` / `child_job_id` relation

Это нужно для:

- append terminal assistant message в правильный thread
- authorisation на cancel
- observability по thread/session без ломания текущего job pipeline

## 5. Required Identifiers

Обязательные идентификаторы следующего implementation шага:

- `user_id`: stable opaque user key
- `session_id`: stable per-login session key
- `thread_id`: stable server-side conversation key
- `message_id`: stable server-side message key
- `job_id`: уже существующий async execution key

Требования:

- все идентификаторы должны быть opaque для frontend
- `username` не должен использоваться как primary key для новых thread/message records
- `thread_id` должен передаваться в chat/file-chat contract после migration phase

## 6. Thread Lifecycle

### Create thread

- thread создаётся явно через отдельную операцию или лениво при первом append в session без active thread
- новый thread получает `state=active` для текущей session

### Active

- active thread определяется значением `session.active_thread_id`
- append новых user/assistant messages идёт только в active non-archived thread

### Inactive

- при переключении на другой thread предыдущий thread становится `inactive` для этой session
- inactive thread остаётся видимым в thread list и доступен для чтения

### Archived

- archived thread не принимает новые messages
- archived thread скрывается из default active list, но остаётся в archive list
- если архивируется active thread, backend обязан снять active pointer и выбрать новый active thread или оставить `null`

### Restored

- restore возвращает thread из `archived` в обычный list
- restored thread не обязан автоматически становиться active, если API явно этого не просит

## 7. Session Semantics

Нормы будущей модели:

- reload страницы в рамках той же session сохраняет `session_id` и `active_thread_id`
- refresh token rotation не должна менять `session_id`
- logout завершает текущую session и очищает только её active-thread binding
- новый login создаёт новый `session_id`
- threads принадлежат пользователю, а не конкретной session
- разные browser sessions одного пользователя делят один набор threads, но имеют независимый `active_thread_id`

Рекомендуемое default поведение для нового session:

- если у пользователя есть неархивированные threads, backend выбирает самый недавно обновлённый как initial active thread
- если threads ещё нет, active thread может быть `null` до первого append

## 8. Backend Responsibilities

Backend должен стать authoritative source of truth для:

- user/session identity binding
- thread list
- active thread pointer
- archive/restore state
- message append semantics
- ownership and access control
- server-side history retrieval per thread
- durable linkage между async job terminal state и thread messages

Backend не должен перекладывать на frontend:

- выбор канонического thread owner
- final authority по active thread
- archive/restore truth
- durable message history

## 9. Frontend Responsibilities

Frontend после будущей реализации отвечает за:

- optimistic UI state
- local render/cache thread list и messages
- visual thread switching
- temporary streaming placeholders
- передачу `thread_id` в chat/file-chat requests

Frontend не должен оставаться authoritative source of truth для:

- создания durable thread identifiers
- хранения единственного real thread list
- определения active thread после reload/login

## 10. High-level API / Contract Sketch

Это не финальная OpenAPI-спецификация, а минимальный contract sketch для следующего implementation шага.

### Session bootstrap

- `GET /api/session`
- возвращает:
  - `user`
  - `session_id`
  - `active_thread_id`
  - optional feature flags / capability markers

### List threads

- `GET /api/threads`
- current runtime already implements a minimal version of this endpoint for non-archived threads
- параметры:
  - `include_archived=false` по умолчанию
- возвращает summary list:
  - `thread_id`
  - `title`
  - `state`
  - `updated_at`
  - `last_message_at`
  - `preview`

### Create thread

- `POST /api/threads`
- current runtime already implements a minimal create-thread endpoint without archive/session semantics
- создаёт новый empty thread или thread с initial user message
- может сразу сделать его active для текущей session

### Set active thread

- `POST /api/threads/{thread_id}/activate`
- обновляет `session.active_thread_id`

### Get thread messages

- `GET /api/threads/{thread_id}/messages`
- current runtime already implements this endpoint for thread-aware message bootstrap
- пагинация определяется implementation step, но API должен поддерживать cursor/limit

### Append regular chat message

- существующий `POST /api/chat`
- future-compatible payload:
  - `prompt`
  - optional `model`
  - optional `thread_id`
- если `thread_id` не передан:
  - backend использует `session.active_thread_id`
  - если его нет, backend создаёт новый thread

### Append file-chat message

- существующий `POST /api/chat_with_files`
- future-compatible form fields:
  - `message`
  - optional `model`
  - optional `thread_id`
  - `files[]`
- parser path, queue, root/child jobs и observability сохраняются как есть; меняется только authoritative thread binding

### Archive thread

- `POST /api/threads/{thread_id}/archive`

### Restore thread

- `POST /api/threads/{thread_id}/restore`

### Clear active thread

- существующий `POST /api/chat/clear`
- migration target:
  - временно остаётся compatibility alias
  - current runtime уже использует thread-aware semantics для выбранного `thread_id`
  - future session model должна доопределить поведение, когда `thread_id` не передан и используется `session.active_thread_id`

## 11. Совместимость с текущим username-based поведением

Будущая реализация обязана сохранить:

- текущий auth/session contract
- current `username` normalization
- текущие chat и file-chat endpoints как минимум на compatibility layer
- parser path и legacy fallback behavior
- SSE streaming contract
- cancel path по `job_id`
- upload observability и parser resilience behavior

Что меняется:

- history больше не должен грузиться только по `chat:{username}`
- append assistant reply больше не должен зависеть только от `username`
- frontend thread snapshots перестают быть единственным местом, где вообще существуют threads

## 12. Migration Plan

Минимально безопасный migration path:

1. Зафиксировать уже выполненный переход на `thread_id` в `POST /api/chat`, `POST /api/chat_with_files`, worker append и parser child flows.
2. Зафиксировать уже выполненный переход на per-thread history storage и server-side thread registry как primary model.
3. Зафиксировать уже выполненный backend truth bootstrap для thread list через `/chat`, `GET /api/threads`, `POST /api/threads` и `GET /api/threads/{thread_id}/messages`.
4. Добавить `session_id` в auth/session contract и сделать backend authoritative owner of persisted `active_thread_id`.
5. Добавить недостающие thread APIs для activate/archive/restore, не ломая текущие chat/file-chat flows.
6. Убрать остаточную зависимость от `chat:{username}` как compatibility bridge после стабилизации и миграции старых данных.

Текущая runtime policy для legacy history:

- legacy `chat:{username}` не является primary source of truth
- при первом bootstrap/read/write/list для explicit `default` thread legacy bucket детерминированно переносится в `chat:{username}:default`
- после успешного переноса legacy key удаляется сразу, а thread registry синхронизируется с `default`
- повторные bootstrap/read операции читают уже explicit per-thread bucket и не делают repeated re-migration

Критично для migration:

- file-chat и parser path не должны менять свои validated queue/root/child semantics
- cancel должен продолжать работать по `job_id`
- observability должна суметь связать `job_id` с `thread_id`, но без разрыва текущих log contracts

## 13. Explicit Non-goals

В рамках `4.1` сознательно не делаются:

- реализация storage backend
- выбор конкретной SQL schema
- полный Redis key design
- перенос auth на новый механизм
- изменение parser/public flags
- изменение UI behavior
- message edit/delete semantics
- shared threads between users
- RAG/document knowledge base

## 14. Open Questions For The Next Step

- где физически хранить thread/message records: Redis-only, SQL, или hybrid
- нужен ли soft-delete для messages или только archive на уровне thread
- нужна ли server-side pagination с message windows по умолчанию
- как именно хранить assistant partial state: durable draft или only terminal message
- нужно ли сохранять file metadata per message в полном виде или только compact summary

## 15. Acceptance Criteria For The Future Implementation Step

Следующий implementation step должен считаться корректным, если:

- backend уже остаётся source of truth для thread list; следующий шаг должен сделать его source of truth и для persisted active thread внутри session
- reload не теряет active thread внутри одной session за счёт session-scoped persisted pointer, а не только за счёт thread-aware bootstrap
- logout не удаляет threads пользователя
- archive/restore работают как серверные операции
- обычный chat и file-chat append идут в конкретный `thread_id`
- parser path и async jobs корректно привязываются к thread/message context
- legacy compatibility для существующих endpoints сохраняется на migration phase

# Quota Model Direction

Этот документ фиксирует design-level направление для шага `P5.3`: как проект должен трактовать per-user и per-group quotas, не создавая ложного впечатления, что quota platform уже внедрена в runtime.

Статус документа:

- design direction selected
- runtime implementation not yet done
- это не quota enforcement rollout
- это не ORM / Alembic plan
- это не runtime PostgreSQL wiring
- это не queue refactor

## 1. Подтверждённые текущие факты

По текущему runtime-коду уже существуют:

- Redis-backed `AsyncRateLimiter`
- queue saturation / backpressure checks
- scheduler-side capacity admission
- AD-group-based model access policy
- parser/file-chat limits и budgets

Но при этом:

- нет отдельной quota platform
- нет per-user quota metadata
- нет per-group quota metadata
- нет durable usage counters
- нет end-to-end quota enforcement contract

Это означает, что current runtime already has throttling and entitlement primitives, но не полноценную quota model.

## 2. Entitlement vs Throttling / Quota

`P5.3` должен явно разделять две разные области.

### Entitlement

Entitlement отвечает на вопрос:

- какие model categories и модели пользователь вообще имеет право использовать

Current runtime fact:

- это уже partially implemented через policy files + AD group mapping

### Throttling / Quota

Throttling/quota отвечает на вопросы:

- сколько запросов можно сделать
- сколько job'ов можно держать одновременно
- какие heavy-path budgets допустимы
- когда нужно hard deny, а когда soft throttle

Current runtime fact:

- это ещё не собрано в отдельную quota platform

## 3. Quota Matrix

| Quota dimension | Current runtime fact | Target owner | Likely enforcement point | Short rationale | Transition note |
|---|---|---|---|---|---|
| requests per user | Есть только rate limiting по `username` | Persistent DB for metadata, Redis for transient counters | `app` entrypoints | Это closest existing primitive для user-level throttling | Current rate limiter не равен полной quota model |
| requests per group | Не реализовано | Persistent DB for policy metadata | `app` entrypoints | Group throttling требует явной quota policy | Нужен отдельный design choice по subject normalization |
| concurrent jobs per user | Не реализовано как user quota | Persistent DB for policy metadata | `gateway.enqueue_job` | Ограничение должно происходить до постановки job в queue | Current scheduler admission не решает per-user fairness |
| concurrent jobs per group | Не реализовано | Persistent DB for policy metadata | `gateway.enqueue_job` | Это group-level fairness / safety control | Нужна future subject model для групп |
| model access by group | Уже partially implemented как entitlement | Persistent DB target for durable entitlement metadata | auth model resolution | Это entitlement primitive, а не quota counter | Policy-files runtime остаётся до отдельного implementation step |
| queue admission limit | Уже есть target-wide overload guard | Redis control-plane runtime state + design policy outside queue | `gateway.get_queue_pressure()` / `enqueue_job()` | Это service protection, не per-user/per-group quota | Не считать текущий queue saturation полноценной quota semantics |
| per-model budget | Не реализовано | Persistent DB for policy metadata | auth model resolution + enqueue hook | Нужен явный budget per model/category | Сейчас есть только allow/deny по policy catalog |
| per-time-window budget | Есть частично как rate limit window | Persistent DB for quota policy, Redis for transient window counters | `app` entrypoints | Это естественное расширение existing rate limiter primitive | Требует явного quota contract, а не только `RATE_LIMIT_*` |
| file-chat heavy-path budget | Частично есть как parser/file limits and budgets | Persistent DB for quota policy metadata | file-chat / parser entrypoints | Heavy path должен иметь отдельную quota semantics поверх existing file guards | Current file limits не равны user/group quota |
| admin/operator override | Не реализовано как quota feature | Later policy metadata | later design | Override требует явной operator policy | Existing admin checks не являются quota bypass contract |
| daily/monthly usage metadata | Не реализовано | Persistent DB | later durable usage layer | Это durable accounting data | Не внедряется на `P5.3` runtime-wise |
| hard deny vs soft throttle behavior | Есть частично и фрагментарно | Design-level policy now, future runtime later | `app` / `gateway` / auth hooks | Нужна явная matrix по реакциям на quota breaches | Сейчас поведение разрознено: `429`, `503`, model deny |

## 4. Existing Hooks For Future Enforcement

Будущий quota layer уже имеет очевидные hook points в текущем runtime:

- `app` entrypoints для обычного chat и file-chat
- `gateway.enqueue_job()` до постановки job в queue
- auth/model resolution path для entitlement checks
- file-chat/parser entrypoints для heavy-path controls

Важно:

- текущий `AsyncRateLimiter` может быть только primitive building block
- текущий scheduler admission остаётся capacity/control-plane guard
- эти hook points не означают, что quota enforcement уже реализован

## 5. Future Durable Owner

По уже зафиксированным `P5.1` и `P5.2`:

- durable quota metadata должна принадлежать future persistent relational DB

Сюда входят:

- quota policy definitions
- subject-level bindings для user/group scopes
- usage metadata
- daily/monthly accounting metadata
- override metadata, если она будет нужна

При этом Redis может остаться transient helper layer для:

- short-lived counters
- request window evaluation
- control-plane side throttling helpers

Но `P5.3` не внедряет этот runtime split, а только фиксирует design direction.

## 6. Later / Unclear Items

На `P5.3` сознательно остаются later / unclear:

- per-group quota subject normalization
- admin/operator override semantics
- daily vs monthly reset rules
- attachment-related quotas
- exact migration/runtime rollout order
- durable storage для partial/intermediate usage state, если она понадобится позже

Эти вопросы нужно зафиксировать как open design items, а не silently считать решёнными.

## 7. Explicit Non-goals

В рамках `P5.3` сознательно не делаются:

- runtime quota enforcement
- DB schema
- ORM / Alembic
- new APIs
- UI changes
- queue refactor
- dashboard / load testing

Также `P5.3` не означает, что:

- quotas уже работают end-to-end
- persistent quota metadata уже хранится в БД
- quota enforcement уже встроен в gateway/app
- TEST validation для quotas уже была

## 8. Source Of Truth After P5.3

После этого design step source of truth должен читаться так:

- entitlement already exists only as a partial runtime primitive
- throttling/quota model теперь описана отдельно и не смешивается с entitlement
- future durable owner для quota metadata уже понятен: persistent DB
- current runtime остаётся без quota platform до следующего implementation step

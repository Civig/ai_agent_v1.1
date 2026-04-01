# Storage Ownership Split

Этот документ фиксирует design-level ownership split для шага `P5.2`: какие категории состояния остаются под управлением Redis, а какие должны перейти в будущий persistent relational store.

Статус документа:

- design ownership selected
- runtime implementation not yet done
- это не ORM rollout
- это не Alembic/migrations plan
- это не runtime PostgreSQL wiring
- это не data migration implementation

## 1. Контекст

После `P5.1` в репозитории уже зафиксировано:

- PostgreSQL выбран как target durable relational database для dialog/message/meta entities
- текущий runtime остаётся Redis-first и фактически Redis-only для storage-critical частей
- ownership split между Redis и будущим persistent store ещё не был оформлен как отдельная design matrix

Этот документ закрывает именно ownership decision. Он не означает, что persistent DB уже подключена в runtime.

## 2. Подтверждённые current runtime facts

По текущему коду:

- chat history хранится в Redis через `AsyncChatStore`
- thread registry тоже хранится в Redis
- queue/job payloads и scheduler/worker control plane живут в Redis
- event streams, heartbeats/leases и dispatch/processing coordination живут в Redis
- rate limiting живёт в Redis
- token revocation живёт в Redis
- model access сейчас определяется через policy files и group mapping, а не через persistent DB
- quota metadata как durable runtime layer не реализована
- audit metadata как durable runtime layer не реализована

## 3. Ownership Matrix

| Категория | Current runtime fact | Target owner | Почему | Transition note |
|---|---|---|---|---|
| chat history | Redis `AsyncChatStore` | Persistent DB | Это durable conversation data, а не control-plane state | До implementation step текущий Redis path остаётся source of truth |
| thread registry | Redis sorted set / registry | Persistent DB | Это durable dialog metadata и thread list truth | Текущий Redis registry остаётся runtime truth до отдельного migration step |
| user/thread/message records | Не реализованы как отдельные persistent records | Persistent DB | Нужны first-class durable entities и нормальные связи ownership | Сейчас runtime использует `username` + Redis buckets как compatibility model |
| queue/job payloads | Redis | Redis | Это transient async execution state | Не входит в durable DB ownership scope |
| dispatch/processing state | Redis | Redis | Это control-plane coordination | Не refactor'ится на `P5.2` |
| event streams | Redis | Redis | Это ephemeral delivery/state stream для SSE/job observation | Не становятся durable source of truth |
| heartbeats/leases | Redis | Redis | Это worker/scheduler orchestration state | Остаются transient control-plane данными |
| rate limiting | Redis | Redis | Это runtime throttling, а не durable business entity | Не переносится в persistent DB на этом шаге |
| token revocation | Redis | Redis | Это auth control-plane state с TTL semantics | Не означает ввод полной session DB |
| session-ish/auth state beyond token revocation | JWT cookies + Redis revocation only | Later / unclear | Полная session platform вне scope `P5.2` | Нужен отдельный design step, если проект пойдёт в server-side session persistence |
| model entitlements / access mapping | Сейчас derived из policy files и AD group mapping | Persistent DB | Это durable authorization metadata для multi-user growth | Policy-files runtime не ломается на `P5.2`; persistent ownership пока design-only |
| quota metadata | Не реализована | Persistent DB | Это durable user/thread/model usage metadata, а не transient state | Runtime quota enforcement не входит в этот шаг |
| audit metadata | Не реализована как durable store | Persistent DB | Нужен persistent operator/security trail | Structured logs не заменяют durable audit ownership |

## 4. Boundary Between Redis And Persistent DB

### Durable conversation/meta boundary

В persistent DB целятся категории, которые должны переживать:

- process restarts
- rollout новых runtime components
- multi-user growth
- будущую нормальную ownership model `user -> thread -> message`

Это означает, что будущий persistent layer должен быть authoritative owner для:

- `user`
- `thread`
- `message` / chat history
- `model entitlement / access mapping`
- `quota metadata`
- `audit metadata`

### Redis control-plane boundary

Redis остаётся authoritative owner для transient runtime coordination:

- queues
- job state
- dispatch / processing coordination
- event streams
- heartbeats / leases
- rate limiting
- token revocation
- прочего transient control-plane state

Это означает, что Redis не должен оставаться long-term durable owner для dialog/message entities после будущего implementation rollout.

## 5. Later Or Unclear Items

Следующие области сознательно не lock'аются как fully resolved ownership на `P5.2`:

- `session-ish/auth state` beyond token revocation
- attachment/blob/file object storage strategy
- exact migration mechanics между Redis history и будущим persistent DB
- нужен ли временный dual-read bridge на migration phase
- нужен ли отдельный durable store для assistant partial state

Для этих пунктов на `P5.2` достаточно зафиксировать только то, что они outside current ownership lock.

## 6. Required Future Boundary

Следующий implementation slice после `P5.2` должен вводить не сразу полный storage refactor, а минимальную boundary между:

- durable conversation/meta storage
- Redis control plane

На design-уровне это означает:

- нужен отдельный storage/repository boundary для durable entities
- Redis-backed queue/runtime orchestration не должен смешиваться с future durable entity ownership
- conversation/meta read-write path должен быть отделён от queue/scheduler path

Этот документ сознательно не фиксирует названия классов, ORM-модели или migration framework.

## 7. Explicit Non-goals

В рамках `P5.2` сознательно не делаются:

- ORM rollout
- Alembic/migrations
- runtime PostgreSQL wiring
- actual data migration
- dual-write implementation
- queue/control-plane refactor
- quota runtime enforcement
- dashboard/load testing
- compose/install changes

Также `P5.2` не означает, что:

- PostgreSQL уже подключён
- DB schema уже существует в репозитории
- migration framework уже добавлен
- persistent runtime read/write path уже работает
- TEST validation для persistent DB уже была

## 8. Source Of Truth After P5.2

После этого design step source of truth должен читаться так:

- current runtime ownership for storage-critical paths всё ещё Redis-based
- target durable ownership для dialog/message/meta entities выбрана за persistent relational DB
- Redis ownership фиксируется как control-plane / transient runtime ownership
- actual implementation, migration и runtime integration остаются следующими шагами roadmap

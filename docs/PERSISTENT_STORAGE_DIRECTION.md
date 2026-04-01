# Persistent Storage Direction For Dialogs

Этот документ фиксирует design-level решение для шага `P5.1`: какое постоянное хранилище должно стать primary durable store для диалогов и связанных метаданных.

Статус документа:

- design choice selected
- runtime implementation not yet done
- это не ORM rollout
- это не Alembic/migrations plan
- это не compose/install integration

## 1. Подтверждённые текущие факты

По текущему runtime-коду:

- chat history хранится в Redis через `AsyncChatStore`
- thread registry тоже хранится в Redis
- queue / scheduler / worker control plane живут в Redis
- token revocation и часть session-ish runtime state тоже живут в Redis
- persistent DB layer в runtime не внедрён
- SQLAlchemy / Alembic / DB URL / migrations в runtime-коде отсутствуют

Это означает, что текущий runtime остаётся Redis-first и фактически Redis-only для storage-critical частей.

## 2. Выбранное направление

Для production-grade durable entities выбирается:

- PostgreSQL как целевая persistent relational database

Это design choice, а не утверждение, что PostgreSQL уже подключён в runtime.

## 3. Почему именно PostgreSQL

Это направление подходит текущему проекту по следующим причинам:

- проекту нужны durable dialog/message/meta entities, а не только ephemeral runtime state
- roadmap уже ушёл в server-side thread/session direction и требует нормальной модели ownership и связей
- target на `100+ users` делает Redis-only history/storage модель слишком хрупкой как единственный durable store
- реляционная модель лучше подходит для `user -> thread -> message`, model access mappings, quotas и audit metadata
- PostgreSQL даёт прозрачную схему данных и предсказуемый multi-user growth path без выдумывания собственной data platform поверх Redis
- выбор не ломает текущий validated runtime, потому что на `P5.1` это только design-level решение

## 4. First-class Persistent Entities

Следующие сущности должны стать first-class persistent entities в будущем implementation scope:

- `user`
- `thread`
- `message`
- `model entitlement / access mapping`
- `quota metadata`
- `audit metadata`

Смысл этого выбора:

- `user`, `thread`, `message` образуют durable conversation model
- `model entitlement / access mapping` не должен оставаться только derived runtime decision
- `quota metadata` должна жить в persistent store, если проект пойдёт в controlled multi-user growth
- `audit metadata` нужна как durable operator/security trail, а не только как transient logs

## 5. Что остаётся в Redis

Даже после будущего persistent storage rollout Redis должен остаться control-plane и transient runtime layer для:

- queues
- job state
- dispatch / processing coordination
- event streams
- heartbeats / leases
- rate limiting
- token revocation
- transient control-plane state
- временный compatibility/migration bridge на переходных implementation steps

Это означает:

- Redis не убирается из системы на `P5.1`
- Redis не становится primary durable store для dialog/message entities

## 6. Что явно НЕ реализовано на P5.1

В рамках этого шага сознательно НЕ делаются:

- внедрение ORM
- внедрение Alembic
- schema rollout
- compose/install changes
- runtime history migration в БД
- quota enforcement runtime
- broad storage refactor
- замена validated Redis runtime path

Также этот шаг НЕ означает, что в репозитории уже есть:

- live PostgreSQL connection
- DB URL contract
- migrations framework
- persistent runtime read/write path для dialogs

## 7. Ownership Split Follow-up

Следующий design шаг после `P5.1` уже не должен выбирать БД заново. Он должен зафиксировать ownership split между:

- Redis как control-plane / transient runtime owner
- persistent relational DB как target durable owner для dialog/message/meta entities

Этот split отдельно оформляется в [STORAGE_OWNERSHIP_SPLIT.md](STORAGE_OWNERSHIP_SPLIT.md).

## 8. Минимальный безопасный следующий implementation scope

После `P5.1` минимальный безопасный следующий шаг должен быть уже не про выбор направления, а про узкий groundwork для future persistent layer.

Он должен:

- ввести минимальную storage abstraction boundary
- определить first implementation slice для durable entities
- не ломать текущий Redis-backed runtime
- не тащить quota runtime, dashboard или broad migration framework раньше времени

До этого момента текущий source of truth остаётся таким:

- runtime storage для chat/thread/job state по-прежнему Redis-based
- PostgreSQL выбран как target durable store, но не внедрён

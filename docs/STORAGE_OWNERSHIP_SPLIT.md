# Storage Ownership Split

Этот документ больше не должен исходить из предпосылки, что runtime всё ещё purely Redis-only. В текущем baseline уже существует Redis/PostgreSQL transition layer, поэтому ниже фиксируется именно текущий implemented ownership boundary и оставшиеся gaps.

## Статус документа

- ownership direction выбрана
- runtime transition baseline уже реализован
- PostgreSQL conversation path уже существует
- Redis control-plane ownership по-прежнему остаётся актуальным
- final authoritative cutover ещё не завершён

## 1. Текущий implemented transition baseline

По текущему коду уже существуют:

- Redis-backed control plane
- PostgreSQL-backed conversation thread/message store
- dual-write coordinator для conversation writes
- DB-backed read cutover для thread list и thread messages
- shadow compare / parity hooks
- Redis fallback semantics при unavailable/mismatch conditions

Это означает:

- current runtime уже не purely Redis-only
- current runtime ещё не fully PostgreSQL-authoritative
- ownership сейчас transitional

## 2. Ownership Matrix

| Категория | Current runtime fact | Current owner | Target owner | Transition note |
|---|---|---|---|---|
| chat history / thread messages | Redis compatibility path + DB-backed read/dual-write groundwork | Transitional | Persistent DB | При mismatch/error runtime всё ещё может fallback'иться к Redis |
| thread registry / thread summaries | Redis registry + DB-backed read cutover | Transitional | Persistent DB | DB path уже существует, но final cutover ещё не объявлен завершённым |
| thread/message relational records | PostgreSQL schema и store уже есть | Persistent DB groundwork | Persistent DB | Это implemented baseline, но не полная platform completion |
| queue/job payloads | Redis | Redis | Redis | Это transient async execution state |
| dispatch/processing state | Redis | Redis | Redis | Это control-plane coordination |
| event streams | Redis | Redis | Redis | Это ephemeral delivery/state stream |
| heartbeats/leases | Redis | Redis | Redis | Это orchestration state |
| rate limiting | Redis | Redis | Redis | Это runtime throttling, не durable business entity |
| token revocation | Redis | Redis | Redis | TTL-based auth control-plane state |
| session-ish/auth state beyond token revocation | JWT + Redis revocation | Later / unclear | Later / unclear | Вне текущего ownership lock |
| model entitlements / access mapping | Сейчас derived из policy files и AD group mapping | Derived runtime | Persistent DB later | Future durable authorization metadata |
| quota metadata | Не реализована как durable runtime layer | Later | Persistent DB later | Вне current rollout |
| audit metadata | Не реализована как durable runtime layer | Later | Persistent DB later | Structured logs не заменяют durable audit store |

## 3. Что уже зафиксировано надёжно

Уже можно считать зафиксированным:

- Redis остаётся control-plane и transient runtime owner
- conversation thread/message relational storage идёт в PostgreSQL path
- runtime уже умеет работать с DB-backed conversation layer
- ownership split больше нельзя описывать как “чисто будущий”

## 4. Что ещё не считается завершённым

Пока рано утверждать, что полностью решены:

- финальный authoritative owner для всех conversation reads/writes без Redis compatibility bridge
- migration completion semantics для legacy Redis conversation data
- durable ownership для user/quota/audit entities
- session platform beyond current JWT + revocation baseline

## 5. Source Of Truth Now

После текущих implementation шагов source of truth должен читаться так:

- Redis остаётся owner для control-plane / transient runtime state
- PostgreSQL уже является implemented conversation persistence path
- conversation ownership сейчас transitional, а не fully finalized
- следующий storage step должен закрыть именно final authority, migration completion и remaining durable entities

# Persistent Storage Direction For Dialogs

Этот документ больше не должен читаться как pure future-only note. Выбранное направление уже partially implemented в runtime baseline, но ещё не доведено до финальной authoritative persistence platform.

## Статус документа

- PostgreSQL direction остаётся выбранным durable storage target
- runtime groundwork уже реализован
- compose/install wiring уже существует
- thread/message schema и store уже существуют
- dual-write / read-cutover / shadow-compare groundwork уже существует
- ownership всё ещё transitional и не считается окончательно завершённым

## 1. Подтверждённые текущие факты

По текущему runtime-коду уже есть:

- Redis path для control-plane state и compatibility conversation path
- `postgres` service в `docker-compose.yml`
- `PERSISTENT_DB_*` flags в config/runtime
- SQLAlchemy-based conversation persistence package в `persistence/`
- schema для `conversation_threads` и `conversation_messages`
- app startup wiring для открытия conversation persistence runtime
- DB-backed thread/message reads при включённом cutover
- conversation dual-write coordinator
- shadow-compare / parity hooks

Также важно:

- fresh install baseline пишет persistence profile в `.env`
- existing `.env` values по persistence сохраняются, если они заданы явно
- runtime всё ещё сохраняет Redis fallback semantics при unavailable/mismatch scenarios

## 2. Выбранное направление не изменилось

Для durable conversation/meta entities выбран:

- PostgreSQL как target persistent relational database

Это уже не просто abstract idea. В репозитории есть working groundwork для подключения и использования этого слоя. Но это всё ещё не равнозначно полной финальной миграции всей ownership model.

## 3. Что уже реально реализовано

Текущий implemented baseline уже включает:

- conversation persistence runtime и session factory
- bootstrap schema path
- conversation thread/message store
- DB-backed thread/message read cutover hooks
- dual-write path для conversation updates
- runtime fallback к Redis при проблемах DB path

Это означает:

- репозиторий больше не является Redis-only по conversation baseline
- persistent DB уже не “только direction doc”
- но текущая модель всё ещё transitional

## 4. Что по-прежнему остаётся в Redis

Redis остаётся owner для:

- queues
- job state
- dispatch / processing coordination
- event streams
- heartbeats / leases
- rate limiting
- token revocation
- transient control-plane state
- compatibility conversation bridge там, где authoritative cutover ещё не объявлен завершённым

## 5. Что ещё не завершено

Следующие вещи не стоит переобещать:

- окончательный authoritative ownership cutover conversation data в PostgreSQL без Redis fallback bridge
- finished migration/rollback story для всех conversation entities
- durable `user` entity platform beyond current username-based ownership
- durable quota metadata rollout
- durable audit metadata rollout
- final session storage platform

## 6. Минимально корректная формулировка baseline

Current source of truth должен читаться так:

- PostgreSQL persistent conversation groundwork уже implemented
- Redis больше не является единственным conversation-related path в runtime
- Redis и PostgreSQL сейчас образуют transitional baseline
- final ownership model и migration completion остаются отдельным следующим шагом

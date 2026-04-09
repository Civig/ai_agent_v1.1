# Operator Dashboard Direction

Этот документ теперь фиксирует не future-only идею, а текущий реализованный baseline operator dashboard и оставшиеся gaps. Исторический design intent `P5.5` по-прежнему важен, но source of truth уже должен совпадать с реальным кодом и UI.

## Статус документа

- read-only operator dashboard уже реализован
- route `/admin/dashboard` и dashboard API surfaces уже существуют
- live telemetry, history и events уже реализованы как текущий monitoring surface
- honest no-data / unavailable semantics уже реализованы
- access model остаётся временным и не является production-ready RBAC
- этот документ фиксирует implemented scope, metric boundaries и remaining gaps

## 1. Подтверждённые текущие факты

По текущему runtime-коду уже существуют:

- HTML dashboard route: `/admin/dashboard`
- read-only API endpoints:
  - `/api/admin/dashboard/summary`
  - `/api/admin/dashboard/live`
  - `/api/admin/dashboard/history`
  - `/api/admin/dashboard/events`
- backend guard для dashboard access
- telemetry sampler, history storage и event log path
- frontend monitoring center с обзором, ресурсами, историей и событиями
- honest no-data / unavailable states для telemetry, GPU и history

При этом остаются важные ограничения:

- текущий access gate узкий и временный
- dashboard не следует считать готовым enterprise RBAC surface
- часть метрик показывается как contextual/operator signal, а не как formalized KPI contract
- distributed semantics telemetry sampler всё ещё topology-sensitive

## 2. Dashboard Metric Matrix

| Dashboard metric | Current runtime fact | Ready / derivable / missing | Current source | Current dashboard treatment | Short rationale |
|---|---|---|---|---|---|
| active users | First-class aggregate отсутствует | Missing | Только `username` в job/log contexts | Не обещается как KPI | Сейчас нет надёжного aggregate-count contract |
| jobs in queue | Уже есть | Ready | `gateway.get_runtime_state()` / `get_basic_metrics()` | Уже показывается | Это честный runtime metric |
| avg latency | Есть partial raw surfaces | Derivable | `job_latency_total_ms/count`, terminal timings, logs | Не объявляется стабильным KPI | Нет clean unified aggregate contract |
| active model | Есть low-level signals | Derivable | target `loaded_models`, per-target model refs | Показывается как contextual detail | Есть raw sources, но нет formalized aggregate |
| failures | Есть partial counters/signals | Derivable | `failed_jobs`, terminal failed statuses, logs | Показывается через события и warnings | Current counter coverage не выглядит complete |
| retries | Есть per-job retry semantics | Derivable | `retry_count`, `requeued` events | Остаётся contextual signal | Aggregate отсутствует |
| queue wait | Уже есть | Ready | `compute_queue_wait_ms()`, `queue_wait_ms`, queue logs | Уже показывается | Уже готовый observability signal |
| active jobs in processing | Уже есть | Ready | `ACTIVE_JOBS_ZSET`, `get_runtime_state()`, `get_basic_metrics()` | Уже показывается | Это честный runtime metric |
| parser backlog | Raw source уже есть | Dashboard-ready | `pending["parse:p1"]` | Уже показывается | Источник прозрачен и стабилен |
| chat backlog | Raw source уже есть | Dashboard-ready | `pending["chat:p1"]` | Уже показывается | Аналогично parser backlog |
| overload events | Есть частично | Derivable | `rejected_jobs`, app-level `503`, queue saturation paths | Уже partly surfaced через event log | Это смесь counters и response/log signals |
| cancel count | Aggregate отсутствует | Missing / derivable later | terminal cancelled statuses / logs | Не обещается как KPI | Нужен отдельный aggregate contract |
| timeout count | Aggregate отсутствует | Missing / derivable later | error classification + failed statuses | Не обещается как KPI | Есть классификация, но нет KPI aggregate |
| stale/requeue count | Есть per-event signal | Derivable | `requeued` events, `retry_count` | Остаётся contextual signal | Aggregate отсутствует |
| health / readiness summary | Уже есть | Ready | `/health`, `/health/ready`, `/health/live` | Уже показывается | Это уже operator-facing surface |
| CPU / RAM / GPU / network telemetry | Уже есть как sampler-built view | Ready with no-data semantics | worker/target heartbeats + dashboard sampler | Уже показывается | Это current read-only telemetry contract, но не host-wide observability promise |

## 3. Текущий честный dashboard scope

### Что уже реально входит в baseline

Текущий dashboard уже сейчас честно покрывает:

- health / readiness summary
- queue depth
- active jobs
- workers / workers_working / capacity
- parser backlog и chat backlog
- live CPU / RAM / GPU / network telemetry
- historical telemetry view
- event log из telemetry sampler и transition signals

### Что показывается, но не должно переобещаться

Следующие вещи можно видеть в панели как operator-facing detail, но не надо описывать их как fully formalized KPI platform:

- active models
- contextual bottleneck interpretation
- warnings/event severity rollups
- historical trend reading across telemetry ranges

### Что по-прежнему не нужно притворяться реализованным

- reliable active users metric
- stable unified average latency KPI
- first-class failure / retry / timeout aggregates
- completed dashboard RBAC / claim model
- field-tiered sensitivity split между observer/operator/admin

## 4. Access и sensitivity boundary

Текущая access model должна читаться честно:

- dashboard остаётся operator-only surface
- текущий gate узкий и временный
- это не production-ready role model
- summary/live/history/events раскрывают operational telemetry, history и event context

Из этого следуют практические выводы:

- dashboard не надо позиционировать как “широкий admin portal”
- dashboard не надо открывать широкому кругу пользователей
- следующий access-model step должен быть отдельным и server-side

## 5. Remaining gaps

Для следующего зрелого шага по dashboard всё ещё остаются:

- dedicated dashboard role/claim model
- per-role visibility split между summary и более чувствительной telemetry/history/events частью
- formalized KPI layer для active users / latency / failures / retries
- clearer multi-instance semantics для telemetry sampler
- real operator validation на target topology

## 6. Explicit non-goals текущего baseline

Текущий dashboard baseline сознательно не означает:

- control actions или system-management UI
- Prometheus/Grafana rollout
- broad metrics refactor
- distributed HA telemetry platform
- production-ready RBAC simply because dashboard уже есть

## 7. Source Of Truth Now

После текущих implementation шагов source of truth должен читаться так:

- read-only operator dashboard уже реализован
- dashboard опирается на реальные summary/live/history/events runtime surfaces
- missing или stale telemetry панель должна показывать честно, без synthetic подмены
- metric boundaries по-прежнему нужно читать консервативно
- access model остаётся временным follow-up gap, который нельзя забывать

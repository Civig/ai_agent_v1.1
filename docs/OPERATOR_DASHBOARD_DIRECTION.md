# Operator Dashboard Direction

Этот документ фиксирует design-level направление для шага `P5.5`: какой первый честный operator dashboard scope можно собрать из текущего runtime, не создавая ложного впечатления, что dashboard уже реализован.

Статус документа:

- design direction selected
- current runtime already exposes partial observability surfaces
- runtime dashboard implementation not yet done
- это не UI rollout
- это не new API / endpoint plan
- это не metrics refactor
- это не Prometheus/Grafana rollout

## 1. Подтверждённые current runtime facts

По текущему runtime-коду уже существуют:

- health / readiness payloads
- queue depth и active jobs
- queue wait helpers
- terminal job logs
- parser/file pipeline logs
- worker/target heartbeats

Но при этом:

- нет отдельного operator dashboard artifact
- нет отдельного operator KPI contract
- часть tracker-метрик существует только как derivable signal
- часть tracker-метрик отсутствует как first-class metric

Это означает, что `P5.5` сначала должен честно зафиксировать первый usable dashboard scope, а не притворяться, что полный dashboard уже готов к implementation rollout.

## 2. Dashboard Metric Matrix

| Dashboard metric | Current runtime fact | Ready / derivable / missing | Current source | First dashboard scope decision | Short rationale |
|---|---|---|---|---|---|
| active users | First-class aggregate отсутствует | Missing | Только `username` в job/log contexts | Не включать в first dashboard scope | Сейчас нет надёжного aggregate-count contract |
| jobs in queue | Уже есть | Ready | `gateway.get_runtime_state()` / `get_basic_metrics()` | Включать сразу | Это уже честный runtime metric |
| avg latency | Есть только partial raw surfaces | Derivable | `job_latency_total_ms/count`, terminal timings, logs | Не обещать как clean KPI в first scope | Текущие surfaces не выглядят полным unified latency contract |
| active model | Есть low-level signals | Derivable | target `loaded_models`, per-target model refs | Не обещать как first-class KPI | Есть raw sources, но нет clean aggregate |
| failures | Есть только partial counter/signal | Derivable | `failed_jobs`, terminal failed statuses, logs | Не обещать как clean aggregate | Current counter coverage не выглядит complete |
| retries | Есть per-job retry semantics | Derivable | `retry_count` в job, `requeued` events | Не обещать как first-class KPI | Aggregate отсутствует |
| queue wait | Уже есть | Ready | `compute_queue_wait_ms()`, `queue_wait_ms`, queue logs | Включать сразу | Уже готовый observability signal |
| terminal success rate | Aggregate отсутствует | Derivable | terminal job statuses / logs | Не обещать как first-class KPI | Потребует operator rollup logic |
| active jobs in processing | Уже есть | Ready | `ACTIVE_JOBS_ZSET`, `get_runtime_state()`, `get_basic_metrics()` | Включать сразу | Это честный current runtime metric |
| parser backlog | Raw source уже есть | Derivable and dashboard-ready | `pending["parse:p1"]` | Включать в first scope как backlog slice | Источник уже прозрачен и стабилен |
| chat backlog | Raw source уже есть | Derivable and dashboard-ready | `pending["chat:p1"]` | Включать в first scope как backlog slice | Аналогично parser backlog |
| overload events | Есть частично | Derivable | `rejected_jobs`, app-level `503`, queue saturation paths | Не обещать как clean aggregate | Сейчас это смесь counters и response/log signals |
| cancel count | Aggregate отсутствует | Missing / derivable later | terminal cancelled statuses / logs | Не включать в first scope | Нужен отдельный aggregate contract |
| timeout count | Aggregate отсутствует | Missing / derivable later | error classification + failed statuses | Не включать в first scope | Есть классификация, но нет KPI aggregate |
| stale/requeue count | Есть per-event signal | Derivable | `requeued` events, `retry_count` | Не обещать как first-class KPI | Aggregate отсутствует |
| health / readiness summary | Уже есть | Ready | `/health`, `/health/ready`, `/health/live` | Включать сразу | Это уже operator-facing surface |

## 3. First Honest Dashboard Scope

### Metrics that are already usable now

Первый честный dashboard scope уже сейчас может опираться на:

- health / readiness summary
- jobs in queue
- active jobs in processing
- queue wait
- parser backlog
- chat backlog
- workers / working workers / capacity из readiness payload

Это безопасно, потому что эти сигналы уже имеют явные runtime sources и не требуют придумывать новую telemetry semantics.

### Metrics that are derivable but not yet dashboard-ready

Следующие категории уже имеют raw signals, но пока не должны объявляться как clean operator KPI:

- avg latency
- active model
- failures
- retries
- overload events
- terminal success rate
- stale/requeue count

Причина одна и та же: current runtime даёт pieces of evidence, но не даёт formalized aggregate contract.

### Metrics that are still missing

Следующие категории не должны притворяться реализованными:

- reliable active users
- first-class cancel count
- first-class timeout count

Для них current runtime не даёт отдельного trustworthy operator metric.

## 4. Current Usable Runtime Sources

`P5.5` фиксирует, что без runtime changes уже можно использовать:

- `/health/live`
- `/health/ready`
- `/health`
- `build_ready_payload()` как текущий source для:
  - Redis/scheduler health
  - workers / workers_working
  - capacity
  - pending queues
  - active jobs
  - basic metrics
- queue/job observability helpers:
  - `compute_queue_wait_ms()`
  - `compute_total_job_ms()`
  - `extract_job_observability_fields()`
- structured logs:
  - `job_queue_observability`
  - `job_terminal_observability`
  - `file_parse_observability`

Важно:

- usable runtime source не означает, что метрика уже готова как operator KPI
- raw log signal не равен formalized dashboard metric сам по себе

## 5. Later / Not Yet Formalized Items

На `P5.5` сознательно остаются later / not yet formalized:

- reliable active users metric
- unified avg latency KPI
- clean active model aggregate
- first-class failures / retries / cancel / timeout aggregates
- operator-friendly rollup across chat + parser paths
- возможные future runtime metrics changes, если они понадобятся позже

Эти вопросы нужно фиксировать как later items, а не silently считать уже решёнными.

## 6. Explicit Non-goals

В рамках `P5.5` сознательно не делаются:

- implementation dashboard
- UI changes
- new endpoints
- observability/runtime behavior changes
- metrics refactor
- Redis schema changes
- DB / quota work
- worker refactor
- Prometheus/Grafana rollout
- load testing

Также `P5.5` не означает, что:

- operator dashboard уже реализован
- все tracker metrics уже доступны как first-class runtime metrics
- active users уже считается надёжно
- avg latency уже является полным unified KPI
- failures / retries уже сведены в clean operator aggregate
- TEST validation для `P5.5` уже была

## 7. Source Of Truth After P5.5

После этого design step source of truth должен читаться так:

- current runtime already has enough observability to define a first honest dashboard scope
- first dashboard scope должен опираться только на ready metrics и explicit health/readiness surfaces
- derivable and missing metrics должны быть явно помечены и не должны притворяться implemented
- implementation dashboard остаётся следующим отдельным шагом roadmap

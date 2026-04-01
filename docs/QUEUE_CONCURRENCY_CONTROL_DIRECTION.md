# Queue And Concurrency Control Direction

Этот документ фиксирует design-level направление для шага `P5.4`: как проект трактует queue depth, concurrency controls и overload behavior, не создавая ложного впечатления, что в runtime уже внедрён новый отдельный control layer.

Статус документа:

- design direction selected
- current runtime already contains partial controls
- runtime implementation not yet unified as a new standalone control layer
- это не queue refactor
- это не worker/scheduler/gateway rewrite
- это не Redis schema change
- это не load-testing rollout

## 1. Подтверждённые current runtime facts

По текущему runtime-коду уже существуют:

- derived queue backpressure через `_dynamic_queue_limit()`
- app-level overload response `503` с `retry_after`
- gateway-level enqueue rejection при saturation
- scheduler-side admission по `active_jobs`, `reserved_tokens`, VRAM, RAM и CPU
- deadline / timeout / cancel propagation
- lease renewal и stale-job recovery
- bounded retry / requeue control
- parser child duplicate protection
- queue / terminal observability

Но при этом:

- нет отдельного first-class fixed hard cap contract для queue depth
- нет отдельного explicit global concurrent-jobs contract
- нет отдельного explicit worker concurrency knob
- parser path и direct chat path различаются по lifecycle

Это означает, что current runtime already has meaningful controls, но `P5.4` нужен для formalized control contract, а не для изобретения controls с нуля.

## 2. Control Matrix

| Control area | Current runtime fact | Explicit or derived | Current enforcement point | Official `P5.4` contract wording | Short rationale |
|---|---|---|---|---|---|
| max queue depth | Queue boundary считается через `_dynamic_queue_limit()` | Derived | `gateway.get_queue_pressure()` / `gateway.enqueue_job()` | Текущий queue-depth contract считается topology-derived, а не fixed hard cap | Уже есть предсказуемый boundary, но он зависит от active topology |
| queue saturation response | App возвращает `503` и `retry_after` | Explicit | `/api/chat`, `/api/chat_with_files` | При saturation пользователь получает fast-fail overload response до enqueue | Это уже user-visible contract |
| enqueue rejection path | Gateway режет enqueue с `503 "LLM queue is saturated"` | Explicit | `LLMGateway.enqueue_job()` | Backend hard-reject сохраняется как current overload guard | Это защищает Redis control plane от неограниченного backlog |
| max concurrent jobs globally | Ограничение получается через admission и `ACTIVE_JOBS_ZSET` | Derived / partial | scheduler admission + target usage accounting | Текущий global concurrency contract считается capacity-derived, а не отдельным fixed global cap | В runtime есть фактическое ограничение, но не отдельный knob |
| max concurrent jobs per worker | Отдельного hard cap не найдено | Not yet formalized | worker loop + dispatch claim lifecycle | Пока не считать per-worker concurrency отдельным explicit contract | Current worker lifecycle не равен policy knob |
| worker concurrency setting | Отдельной настройки нет | Not implemented as first-class knob | не найден отдельный config owner | `P5.4` не утверждает существование отдельного worker-concurrency setting | Нельзя документировать несуществующий knob |
| scheduler admission control | Admission уже есть по target capacity и reserved resources | Explicit | `_evaluate_target_admission()` / `try_admit_job()` | Scheduler admission already governs practical concurrency | Это главный текущий mechanical guard |
| parser worker concurrency | Есть parser pool, но без отдельного explicit cap | Partial / derived | parser worker pool + parser-root -> child flow | Parser path считается отдельным lifecycle path с inherited runtime controls | Нужно явно не смешивать parser path с direct chat path |
| chat worker concurrency | Есть chat worker pool, но без отдельного explicit cap | Partial / derived | chat worker loop + scheduler admission | Chat path использует те же admission/backpressure controls без отдельного first-class per-worker cap | Practical concurrency уже ограничивается механикой admission |
| deadline / timeout | Есть queue/inference/parser deadlines и timeouts | Explicit | app wait path, worker runtime, stale-job reaper | Deadline/timeout semantics уже входят в current control contract | Это часть overload/failure containment |
| cancel propagation | Cancel path проходит app -> gateway -> worker | Explicit | cancel endpoint, cancel flags, worker checks | Cancel propagation считается обязательной частью control plane | Это уже deterministic behavior |
| lease / stale-job recovery | Есть lease renewal и stale-job requeue/fail logic | Explicit | `lease_loop()` / `requeue_stale_jobs()` | Lease/recovery semantics входят в current reliability contract | Это ограничивает залипание running jobs |
| retry / requeue control | Есть bounded retries через `SCHEDULER_MAX_JOB_RETRIES` | Explicit | `requeue_stale_jobs()` | Retry/requeue остаётся bounded recovery mechanism, а не unlimited replay | Это важный overload/recovery guard |
| duplicate admission protection | Есть parser child dedupe через `enqueue_child_job_once()` | Explicit but path-specific | parser root -> child enqueue | Duplicate protection явно формализуется как parser-specific control, не как общий queue dedupe | Нужно честно зафиксировать scope |
| queue wait observability | Есть `queue_wait_ms` и queue logs | Explicit | `compute_queue_wait_ms()` / `job_queue_observability` | Queue wait timing already belongs to current control observability contract | Это даёт измеримый сигнал деградации |
| overload metrics/logging | Есть rejected/failed counters и terminal/parse logs | Partial but real | gateway metrics + app/worker logs | Overload observability уже существует, но не заменяет отдельный runtime policy layer | Metrics есть, unified operator policy ещё нет |

## 3. Explicit Vs Derived Controls

`P5.4` должен явно различать два класса controls.

### Already explicit in runtime

- app-level overload `503` responses
- gateway-level enqueue rejection
- scheduler admission checks
- deadlines / timeouts
- cancel propagation
- lease renewal
- stale-job recovery
- bounded retry count
- queue / terminal observability logs

### Still derived or only partially formalized

- queue-depth boundary через `_dynamic_queue_limit()`
- effective global concurrency через target admission and resource accounting
- parser/chat worker concurrency behavior через lifecycle and topology
- overload semantics как единый operator-facing contract

Это различие важно: `P5.4` formalizes current contract, но не должен притворяться, что derived controls уже превратились в отдельные fixed hard caps.

## 4. Overload Behavior Contract

Текущий runtime уже задаёт следующий overload behavior:

- до enqueue app может вернуть `503 "Сервис перегружен"` с `retry_after`
- во время enqueue gateway может отклонить job с `503 "LLM queue is saturated"`
- queued/running jobs уважают `deadline_at`
- inference и parser path уважают timeout controls
- cancel request должен приводить к terminal cancelled state
- stale running jobs должны либо requeue'иться, либо завершаться failed/cancelled по текущим recovery rules
- retry exhaustion должна приводить к terminal failure, а не к бесконечному replay

Где behavior уже deterministic:

- app overload response
- gateway enqueue rejection
- cancel propagation
- lease renewal / stale-job recovery
- retry exhaustion

Где behavior пока остаётся topology-derived или only partially formalized:

- exact queue boundary при изменении active workers/targets
- exact practical concurrency ceiling
- parser/chat asymmetry при конкуренции за capacity

## 5. Parser Path Vs Direct Chat Path

`P5.4` должен отдельно фиксировать, что parser path отличается от direct chat path.

Direct chat path:

- request сразу попадает в chat/file-chat queue
- scheduler admission и worker execution происходят напрямую

Parser path:

- app ставит parser root job
- `worker-parser` готовит grounded artifacts
- затем parser root enqueue'ит downstream `file_chat` child job

Следствия:

- parser path имеет дополнительную очередь и дополнительный lifecycle stage
- duplicate protection уже есть именно на parser child enqueue
- parser-path concurrency нельзя описывать как точную копию direct chat path

## 6. Later / Not Yet Formalized Items

На `P5.4` сознательно остаются later / not yet formalized:

- fixed hard cap vs derived queue boundary
- explicit per-worker concurrency knob
- explicit global concurrent-jobs contract
- parser/chat asymmetry implications under heavy load
- любые controls, которые сейчас выражены только через scheduler/resource admission
- отдельный operator-facing overload playbook

## 7. Explicit Non-goals

В рамках `P5.4` сознательно не делаются:

- runtime control changes
- new limits in code
- queue refactor
- worker/scheduler/gateway refactor
- Redis schema changes
- DB / quota work
- load testing
- dashboard / operator console

Также `P5.4` не означает, что:

- новый control layer уже внедрён
- fixed worker concurrency knob уже существует
- explicit global concurrent limit уже реализован
- все overload semantics уже полностью unified в runtime
- TEST validation для `P5.4` уже была

## 8. Source Of Truth After P5.4

После этого design step source of truth должен читаться так:

- current runtime queue/concurrency controls already exist and remain the active implementation baseline
- часть controls уже explicit, а часть остаётся derived from topology and scheduler admission
- overload behavior contract описан и больше не размазан по нескольким файлам неявно
- parser path и direct chat path считаются разными lifecycle paths в рамках одного control plane

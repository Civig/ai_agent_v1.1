# Load Benchmark Toolkit

Self-contained harness для benchmark against a live Corporate AI Assistant instance.

## Когда использовать `shared-session`

- smoke / staircase runs
- `5 / 10 / 20` logical users
- когда нужно быстро проверить queue growth, latency и drain behavior
- когда benchmark фокусируется на chat runtime path, а не на login throughput

Важно: в текущем приложении есть user-scoped rate limit (`RATE_LIMIT_REQUESTS=20` за `60s`). Поэтому `50 / 100 / 200` на одном `aitest` login не являются честным capacity benchmark, если пошли `429`.

## Когда нужен `multi-session`

- любой честный benchmark `50 / 100 / 200`
- сценарии, где нельзя упираться в single-user rate limit
- сравнение поведения под real multi-user session fan-out

Для `multi-session` нужен credentials file формата `username:password`. Пример лежит в `sample_users.example.txt`.

## Что toolkit пишет

Только в переданный `--output-dir`:

- `summary.json`
- `requests.csv`
- `wait_table.csv`
- `wait_table.md`
- `health_ready.jsonl`
- `health.jsonl`
- `run.log`
- `raw_sse/*.sse`

## Базовый запуск

### Shared-session

```bash
python tests/load_benchmark/run_benchmark.py \
  --host https://127.0.0.1 \
  --profile 20 \
  --output-dir /tmp/p56_20u \
  --mode shared-session \
  --username aitest \
  --password '<masked>' \
  --warmup \
  --quiet-window-seconds 65 \
  --insecure
```

### Multi-session

```bash
python tests/load_benchmark/run_benchmark.py \
  --host https://127.0.0.1 \
  --profile 100 \
  --output-dir /tmp/p56_100u \
  --mode multi-session \
  --user-file /tmp/bench-users.txt \
  --warmup \
  --quiet-window-seconds 65 \
  --insecure
```

## Что смотреть в `summary.json`

- `successful_requests`
- `failed_requests`
- `timeout_count`
- `rejected_429_count`
- `auth_failure_count`
- `p50_latency_ms`
- `p95_latency_ms`
- `max_queue_depth`
- `max_pending_chat_p1`
- `max_active_jobs`
- `capacity_false_samples`
- `drained`
- `drain_seconds`
- `final_classification`

## Возможные итоговые классификации

- `success`
- `completed_with_queue_pressure`
- `rate_limit_blocked`
- `timeout_blocked`
- `stuck_jobs_detected`
- `auth_blocked`
- `health_blocked`

Toolkit не меняет приложение и не пишет ничего в репозиторий во время runtime run.

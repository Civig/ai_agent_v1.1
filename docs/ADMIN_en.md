# Administration and Operations

## Scope

This document covers day-2 operations for Corporate AI Assistant. It is focused on the current repository implementation and the current Docker Compose deployment model.

## Service Inventory

Baseline stack:

- `corporate-ai-nginx`
- `corporate-ai-assistant`
- `corporate-ai-sso-proxy`
- `corporate-ai-scheduler`
- `corporate-ai-worker-chat`
- `corporate-ai-worker-siem`
- `corporate-ai-worker-batch`
- `corporate-ai-worker-parser`
- `corporate-ai-postgres`
- `corporate-ai-redis`
- `ollama-server`

Optional:

- `corporate-ai-worker-gpu`

## Common Lifecycle Commands

## Release Artifact Baseline

The reproducible production rebuild baseline now consists of:

- the exact git commit
- [requirements.lock](../requirements.lock)
- the pinned `PYTHON_BASE_IMAGE` in [Dockerfile](../Dockerfile)
- pinned `REDIS_IMAGE`, `POSTGRES_IMAGE`, `OLLAMA_IMAGE`, and `NGINX_IMAGE` values in `.env`

Before an intentional update, make sure the change really carries a reviewed lock/image baseline refresh instead of accidental external drift.

### Start the stack

```bash
docker compose up -d
```

### Rebuild and restart

```bash
docker compose up -d --build
```

If you want a reproducible rebuild, first confirm that `.env` is not overriding image references unexpectedly and that [requirements.lock](../requirements.lock) matches the intended release baseline.

### Start with optional GPU worker

```bash
docker compose --profile gpu up -d
```

### Stop the stack

```bash
docker compose down
```

### View container state

```bash
docker compose ps
```

## Logs

### Follow the main services

```bash
docker compose logs -f app scheduler worker-chat nginx
```

### Inspect file-processing behavior

```bash
docker compose logs --tail=200 app worker-parser worker-chat
```

### Inspect GPU-related runtime behavior

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Useful log markers currently implemented in the code:

- `Routing job ... to cpu|gpu`
- `file_parse_observability`
- `job_queue_observability`
- `job_terminal_observability`
- `upload_rejected`
- `Skipping job ... because target_kind mismatch`

## Health Checks

### HTTP health endpoints

```bash
curl -k -i https://127.0.0.1/health/live
curl -k -i https://127.0.0.1/health/ready
curl -k -i https://127.0.0.1/health
```

### What readiness means today

`/health/ready` returns success only when:

- Redis is reachable
- the scheduler heartbeat is fresh
- at least one chat-capable worker is working
- the runtime reports schedulable chat capacity

### Container health

```bash
docker compose ps
```

The Compose health checks use `runtime_healthcheck.py` for `app`, `scheduler`, and workers.

## Operator Dashboard

The current operator dashboard is already implemented as a read-only monitoring surface:

- route: `/admin/dashboard`
- APIs:
  - `/api/admin/dashboard/summary`
  - `/api/admin/dashboard/live`
  - `/api/admin/dashboard/history`
  - `/api/admin/dashboard/events`

Important notes:

- the dashboard uses honest no-data / unavailable states and does not fabricate telemetry
- live/history/events are intended for operator monitoring, not broad user access
- the current access model remains a narrow temporary operator gate rather than production-ready RBAC
- the ordinary operator gate (`ADMIN_DASHBOARD_USERS`) and the local break-glass admin are separate access paths
- in `AUTH_MODE=lab_open`, the dashboard may open through a synthetic lab identity, but the UI shows an explicit warning and that path does not replace the enterprise operator gate
- after the initial forced rotation, a valid local-admin session can open `GET /admin/local/change-password`; a successful `POST /admin/local/change-password` logs that local-admin session out and requires a fresh login with the new password

## Model Operations

### List models

```bash
docker compose exec -T ollama ollama list
```

### Pull a model manually

```bash
docker compose exec -T ollama ollama pull phi3:mini
docker compose exec -T ollama ollama pull gemma2:2b
```

### Run repository bootstrap logic

```bash
./bootstrap_ollama_models.sh
```

`bootstrap_ollama_models.sh` uses a bounded pull timeout and can fall back to a local `models/*.gguf` asset when one is available. If neither pull nor the local asset yields `DEFAULT_MODEL`, the script exits with an explicit failure.

## Queue and Job Lifecycle Checks

### Check scheduler heartbeat

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
```

### Check registered workers

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### Inspect pending queues

Example for chat priority queues:

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p0 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p1 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p2'
```

### Inspect a concrete job

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:job:<job_id>'
```

### What to look for in logs

- `job_queue_observability` for queue wait time
- `job_terminal_observability` for terminal status, inference time, and total job time
- routing logs for CPU/GPU target selection

## File Upload, PDF, and OCR Operations

### Supported upload types

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### Typical file-processing checks

```bash
docker compose logs --tail=200 app worker-parser
```

Look for:

- `file_parse_observability`
- `upload_rejected`
- file-chat acceptance logs

### PDF path notes

The PDF path is part of the current backend implementation. If PDF extraction stops working after environment drift, rebuild the application image:

```bash
docker compose up -d --build app worker-parser worker-chat worker-siem worker-batch
```

### OCR path notes

OCR is currently built into the container image for supported image uploads. If image extraction fails, review `app` logs first before assuming an application logic regression.

## Observability Logs

The repository currently exposes a baseline observability model through structured logs rather than an external telemetry stack.

Key fields currently available include:

- parse timing
- queue wait timing
- inference timing
- total job timing
- model key / model name
- workload class
- target kind
- terminal status
- normalized error type

Current log events to grep:

```bash
docker compose logs --tail=300 app worker-parser worker-chat scheduler | grep -E 'file_parse_observability|job_queue_observability|job_terminal_observability|upload_rejected|Routing job'
```

## Regular Maintenance

Recommended recurring checks:

- `docker compose ps`
- `/health/ready`
- `docker compose exec -T ollama ollama list`
- disk usage for Redis and Ollama volumes
- TLS certificate validity
- `.env` secret rotation according to your internal policy

Recommended after model or infrastructure changes:

- rebuild affected services
- run a login smoke test
- run one regular SSE chat request
- run one file-chat request
- confirm `/health/ready` returns healthy afterward

## Post-Update Smoke Test

Minimal smoke test after updates:

1. `docker compose up -d --build`
2. `docker compose ps`
3. `curl -k https://127.0.0.1/health/ready`
4. log in with a valid AD account
5. send one regular chat request
6. send one file-chat request with a small text or PDF file
7. verify queue drains back to idle

## Degradation Response

### If `/health/ready` degrades

- inspect `app`, `scheduler`, `worker-chat`, `redis`, and `ollama` logs
- verify model availability
- verify scheduler heartbeat
- verify at least one worker heartbeat

### If queue latency grows

- inspect `job_queue_observability`
- check whether workers are healthy
- check whether the selected model exists
- verify that GPU routing is not waiting for an unavailable GPU worker

### If file chat degrades

- inspect `file_parse_observability`
- inspect `upload_rejected`
- verify the file type and size are supported
- inspect worker terminal logs for `error_type`

## Rollback Basics

This repository does not ship a dedicated release-management system. The practical rollback path is:

1. restore a previous known-good repository revision on the host
2. keep or restore the matching `.env`
3. rebuild the stack:

```bash
docker compose up -d --build
```

If models were changed as part of the rollout, also verify the available Ollama model set after rollback.

## Related Documents

- [Install Guide](INSTALL_en.md)
- [Architecture](ARCHITECTURE_en.md)
- [Troubleshooting](TROUBLESHOOTING_en.md)
- [Security Baseline](SECURITY_en.md)
- [README.md](../README.md)

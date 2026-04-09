# Pilot Runbook

## Purpose

This runbook is intended for the pilot handoff and the first operator checks after installation.

## Main URLs

- main application: `https://<host>/`
- liveness: `https://<host>/health/live`
- readiness: `https://<host>/health/ready`
- operator dashboard: `https://<host>/admin/dashboard`

## 5-minute post-install check

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

Expected baseline:

- the stack is up
- `health/ready` is healthy
- at least one model exists
- the scheduler heartbeat is fresh
- at least one chat-capable worker exists

## Quick smoke test

1. open `https://<host>/`
2. log in with a valid AD account through password login
3. send one normal chat request
4. send one file-chat request with a small supported file
5. open `/admin/dashboard`

## How to tell the system is healthy

The system is in a normal state when:

- readiness is green
- login works
- normal chat and file-chat finish without unexpected errors
- dashboard summary/live/history/events open
- the queue returns to idle or near-idle after the smoke test
- the dashboard honestly shows `no-data` / `unavailable` when metrics are temporarily unavailable

## First commands to use during trouble

Main logs:

```bash
docker compose logs --tail=200 app scheduler worker-chat nginx
docker compose logs --tail=200 app worker-parser worker-chat
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Model and queue checks:

```bash
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p0 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p1 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p2'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
```

## First response to common problems

### Login does not work

- check DNS/LDAP/KDC hostname resolution
- inspect `app` logs
- if SSO is being tested, remember that it is a separate validation track, not a baseline assumption

### Chat does not work

- check `ollama list`
- inspect `app`, `worker-chat`, and `scheduler`
- confirm that the selected model is available

### File-chat does not work

- inspect `app` and `worker-parser` logs
- check file type and limits
- look for `file_parse_observability`, `upload_rejected`, and `error_type`

### Dashboard looks empty

- first compare it with `health/ready`, worker heartbeat, and queue state
- remember that honest `no-data` / `unavailable` is not the same as a UI failure

### The GPU pilot degrades

- follow [GPU_VALIDATION_PLAYBOOK_en.md](GPU_VALIDATION_PLAYBOOK_en.md)
- look for routing logs and host-side `nvidia-smi` evidence
- do not treat the mere presence of `worker-gpu` as sufficient proof

## Safe cleanup commands to keep nearby

```bash
bash uninstall.sh --dry-run
sudo bash uninstall.sh --dry-run --factory-reset
```

Use `factory-reset` only when you need a manifest-scoped rollback of installer-owned host changes.

## Related documents

- [PILOT_ACCEPTANCE_CHECKLIST_en.md](PILOT_ACCEPTANCE_CHECKLIST_en.md)
- [PILOT_LIMITATIONS_en.md](PILOT_LIMITATIONS_en.md)
- [ADMIN_en.md](ADMIN_en.md)
- [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md)

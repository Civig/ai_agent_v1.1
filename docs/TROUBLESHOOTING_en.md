# Troubleshooting

## Scope

This guide covers common deployment and runtime issues for Corporate AI Assistant in its current Docker Compose form.

Recommended first checks for almost any problem:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat nginx
curl -k -i https://127.0.0.1/health/live
curl -k -i https://127.0.0.1/health/ready
```

## Login Failed or Kerberos Error

### Symptom

- the login page loads, but login fails
- LDAP/Kerberos-related errors appear in `app` logs
- you see errors similar to `No worthy mechs found` or directory lookup failures

### Probable cause

- incorrect LDAP/Kerberos settings in `.env`
- hostname/SPN mismatch
- missing or incorrect `deploy/krb5.conf`
- AD/KDC connectivity issue

### How to check

```bash
docker compose logs --tail=200 app
docker compose exec -T app bash -lc 'cat /etc/krb5.conf'
docker compose exec -T app bash -lc 'getent hosts <ldap-hostname>'
```

If available, run the repository auth diagnostic:

```bash
AUTH_CHECK_PASSWORD='***' ./diagnose_auth_runtime.sh <username>
```

### How to fix

- verify `.env` LDAP/Kerberos values
- verify the LDAP hostname resolves inside containers
- verify the runtime hostname matches the AD SPN expectations
- regenerate or correct `deploy/krb5.conf`

## `health/ready` Is Not Healthy

### Symptom

- `/health/ready` returns `503`
- `docker compose ps` shows unhealthy services

### Probable cause

- Redis is unavailable
- scheduler heartbeat is missing or stale
- no working chat worker is available
- Ollama or model availability is missing

### How to check

```bash
docker compose ps
docker compose logs --tail=200 redis scheduler worker-chat ollama app
curl -k -i https://127.0.0.1/health/ready
```

### How to fix

- restore the failed container first
- confirm at least one chat worker is healthy
- confirm Ollama has at least one model
- rebuild affected services if runtime drift occurred

## Model Not Found

### Symptom

- chat requests fail even though the stack is up
- model list in the UI is empty or incomplete

### Probable cause

- no Ollama model is installed
- the selected model is not present in the runtime

### How to check

```bash
docker compose exec -T ollama ollama list
docker compose logs --tail=100 app worker-chat
```

### How to fix

```bash
docker compose exec -T ollama ollama pull phi3:mini
./bootstrap_ollama_models.sh
```

## File Upload Rejected

### Symptom

- file upload returns `400`
- file-chat request is rejected before inference

### Probable cause

- unsupported extension
- content-type mismatch
- file too large
- too many files in one request

### How to check

```bash
docker compose logs --tail=200 app | grep upload_rejected
```

### How to fix

- use a supported type: `txt`, `pdf`, `docx`, `png`, `jpg`, `jpeg`
- ensure browser/content-type matches the extension
- reduce file size or file count

## PDF Parsing Issue

### Symptom

- PDF uploads are accepted but file chat fails
- app logs show PDF parser-related failure

### Probable cause

- application image drift
- broken runtime dependency state
- malformed or difficult PDF

### How to check

```bash
docker compose logs --tail=200 app
```

Look for file-parse failures around PDF requests.

### How to fix

```bash
docker compose up -d --build app worker-chat worker-siem worker-batch
```

If the issue is file-specific, test with a simpler PDF first.

## Queue Stuck or Job Never Finishes

### Symptom

- chat stays queued
- no terminal status is reached
- `/health/ready` may still be degraded

### Probable cause

- scheduler heartbeat missing
- no worker capacity
- missing model
- worker or target mismatch

### How to check

```bash
docker compose logs --tail=200 scheduler worker-chat app
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### How to fix

- restore scheduler and worker health
- verify model availability
- inspect `job_queue_observability` and `job_terminal_observability`
- inspect routing logs for CPU/GPU assignment problems

## Worker Not Processing Jobs

### Symptom

- pending jobs exist, but `worker-chat` does not process them

### Probable cause

- worker container unhealthy
- stale or missing worker heartbeat
- target mismatch

### How to check

```bash
docker compose ps
docker compose logs --tail=200 worker-chat scheduler
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### How to fix

- restart or rebuild the worker
- confirm `worker-chat` is healthy
- if GPU routing is enabled, confirm the requested target kind matches available workers

## GPU Worker Does Not Start

### Symptom

- `worker-gpu` is absent or unhealthy
- `docker compose --profile gpu up -d` fails

### Probable cause

- host GPU container support is not ready
- GPU runtime is missing or incomplete on the host

### How to check

```bash
docker compose --profile gpu up -d
docker compose ps
docker compose logs --tail=200 worker-gpu
```

### How to fix

- validate host GPU container support outside the application
- keep the deployment in CPU mode until the host GPU runtime is fixed

## Fallback to CPU Happens

### Symptom

- you expected GPU execution, but logs show CPU routing

### Probable cause

- `GPU_ENABLED=true` is set, but no active GPU worker exists

### How to check

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Look for:

- `GPU routing requested ... falling back to cpu`
- `Routing job ... to cpu`

### How to fix

- start a working `worker-gpu`
- or keep CPU mode intentionally if GPU support is not ready

## `403` Responses

### Symptom

- authenticated actions fail with `403`

### Probable cause

- CSRF mismatch
- expired or invalid session
- revoked token

### How to check

- confirm the browser still has session cookies
- confirm the request includes the CSRF header for modifying endpoints
- inspect `app` logs

### How to fix

- refresh the session
- log in again
- ensure the client sends the CSRF token correctly

## `400` Responses

### Symptom

- request is rejected as invalid

### Probable cause

- invalid request shape
- unsupported upload type
- invalid content-type for the uploaded extension
- excessive file count or file size

### How to check

```bash
docker compose logs --tail=200 app | grep upload_rejected
```

### How to fix

- correct the request payload
- use a supported file type and size

## `500` Responses

### Symptom

- the backend returns `500`

### Probable cause

- unhandled internal error
- environment drift
- model runtime failure

### How to check

```bash
docker compose logs --tail=200 app worker-chat scheduler
```

### How to fix

- identify the failing service from logs
- rebuild the affected service if needed
- rerun a minimal smoke test after recovery

## Related Documents

- [Administration and Operations](ADMIN_en.md)
- [Install Guide](INSTALL_en.md)
- [Architecture](ARCHITECTURE_en.md)
- [Security Baseline](SECURITY_en.md)

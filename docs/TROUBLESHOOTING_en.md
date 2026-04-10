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

## Installer Fails on Docker, PyPI, or Ollama Reachability Checks

### Symptom

- `install.sh` stops during outbound connectivity checks
- errors mention Docker download, Docker registry, PyPI, or Ollama reachability
- package download, Docker pull, or model bootstrap fails before the application is healthy

### Probable cause

- host internet connectivity issue
- host DNS issue
- temporary upstream registry/package-host outage
- Docker/container DNS issue if host checks pass but Docker pulls or later container lookups still fail
- this is a hard blocker for the first deploy, but not necessarily for an already deployed system whose local artifacts are still present

### How to check

```bash
curl -I --max-time 10 https://registry-1.docker.io/v2/
curl -I --max-time 10 https://pypi.org/simple/
curl -I --max-time 10 https://files.pythonhosted.org/
getent hosts registry-1.docker.io
getent hosts pypi.org
getent hosts files.pythonhosted.org
```

If Ollama model bootstrap is the failing step, also check:

```bash
docker compose exec -T ollama ollama list
docker compose logs --tail=100 ollama
```

### How to fix

- if this is the first deploy, or the host is missing required local Docker images / host packages / other artifacts, fix host DNS or HTTPS reachability first and retry the installer only after the host can repeatedly resolve and reach the required endpoints
- if the system has already been deployed and the installer reports post-deploy local repair mode, let it complete the local regenerate/reconfigure steps; network access is only needed in that mode for artifacts that are genuinely missing locally
- if host checks succeed but Docker pulls still fail, continue with the Docker/container DNS checks below
- if the upstream registry or package host is temporarily unavailable, wait and retry later
- if the installer later stops on a missing local package or Docker image, that specific post-deploy step still cannot proceed without network and the artifact must be prepared in advance

## Host DNS, `/etc/resolv.conf`, or `systemd-resolved` Is Wrong

### Symptom

- host lookups for Docker/PyPI endpoints fail
- `/etc/resolv.conf` points to a stub or resolver path that is not actually working on this VM
- DNS behavior changes unexpectedly after reboot or differs from the resolver policy you intended

### Probable cause

- broken host DNS configuration
- `/etc/resolv.conf` points to the wrong resolver file or stale stub listener
- `systemd-resolved` is running, but its upstream DNS settings do not match the host's intended resolver policy

### How to check

```bash
cat /etc/resolv.conf
resolvectl status || systemd-resolve --status || true
getent hosts registry-1.docker.io
getent hosts pypi.org
getent hosts files.pythonhosted.org
```

### How to fix

- align the host DNS configuration with your environment's intended resolver policy before retrying the install
- if `systemd-resolved` is in use, make sure `/etc/resolv.conf` points to the resolver file your host policy expects and that the configured upstream resolvers are healthy
- if `systemd-resolved` is not part of the intended host setup, remove the mismatch instead of leaving a broken stub resolver in place
- retry install only after repeated host lookups return stable results
- this is host infrastructure work, not an application bug

## Host DNS Works But Docker or Containers Still Cannot Resolve

### Symptom

- host `curl`/`getent` works, but Docker pulls still fail
- container-side LDAP or external lookups fail even though host DNS looks healthy
- container DNS instability appears during install or later auth/runtime checks

### Probable cause

- Docker daemon inherited stale or incorrect DNS settings
- container DNS path differs from host DNS
- `systemd-resolved` stub behavior and Docker DNS inheritance are misaligned

### How to check

```bash
cat /etc/docker/daemon.json 2>/dev/null || true
docker info
docker compose exec -T app bash -lc 'getent hosts <ldap-hostname>'
docker compose exec -T app bash -lc 'getent hosts pypi.org || true'
```

### How to fix

- if Docker daemon DNS is explicitly managed in your environment, correct it and restart Docker according to host policy
- keep host DNS and Docker/container DNS aligned before rerunning install or restarting the stack
- if the issue affects only AD lookups from containers, the installer's AD IP override may be an acceptable workaround, but it does not fix general internet or registry reachability problems
- retry install or model bootstrap only after both host and container lookups are stable

## Ollama Model Pull Fails Because of Network or DNS

### Symptom

- `ollama pull` fails, times out, or never completes
- `ollama list` stays empty after install
- `/health/ready` remains degraded because no model was fetched successfully

### Probable cause

- upstream Ollama reachability problem
- host or container DNS problem
- Docker/container egress issue

### How to check

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
docker compose logs --tail=100 ollama
```

### How to fix

- first resolve host/Docker DNS or outbound network issues
- retry `ollama pull` only after the basic Docker/PyPI/host reachability checks succeed
- if the external Ollama endpoint remains unavailable while local DNS and egress are healthy, wait and retry later
- this is outside application scope until the model source is reachable

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
- total file size exceeds the request budget

### How to check

```bash
docker compose logs --tail=200 app | grep upload_rejected
```

### How to fix

- use a supported type: `txt`, `pdf`, `docx`, `png`, `jpg`, `jpeg`
- ensure browser/content-type matches the extension
- reduce file size, file count, or total uploaded payload size

## PDF Parsing Issue

### Symptom

- PDF uploads are accepted but file chat fails
- `app` or `worker-parser` logs show PDF parser-related failure

### Probable cause

- application image drift
- broken runtime dependency state
- malformed or difficult PDF

### How to check

```bash
docker compose logs --tail=200 app worker-parser
```

Look for `file_parse_observability` and parse failures around PDF requests.

### How to fix

```bash
docker compose up -d --build app worker-parser worker-chat worker-siem worker-batch
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

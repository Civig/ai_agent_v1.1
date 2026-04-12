# GPU Validation Playbook

## Purpose

This playbook is for the separate verification of the GPU path on a dedicated GPU host. Until this scenario is completed, GPU must not be treated as a proven pilot capability.

## Verdict classes

- `validated` - the GPU path is proven end to end
- `blocked_by_environment` - the check is blocked by drivers, runtime, or host preparation
- `partially_validated` - part of the scenario passed, but real GPU use or telemetry honesty was not fully proven
- `not_proven` - the stack may have started, but the GPU capability was not proven

## 1. Host preflight

Run on the target GPU host:

```bash
hostname
whoami
pwd
uname -a
nvidia-smi
lspci | grep -Ei 'nvidia|vga|3d'
docker info | grep -i 'Runtimes\|Default Runtime\|nvidia'
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi
```

If external pulls are restricted in your environment, use a pre-approved locally available CUDA utility image with an equivalent `nvidia-smi` check.

Expected result:

- the GPU is detected on the host
- `nvidia-smi` works without errors
- Docker can see the GPU runtime and can run a test container with `--gpus all`

If any item fails, the verdict is immediately `blocked_by_environment`.

## 2. Repo pin and clean tree

The commands below preserve the earlier pilot-package GPU validation reference and are not the current `v1.2.0` release-candidate pin by themselves.

```bash
cd /home/admin_ai/ai_agent_v1.1
git rev-parse --verify <historical-pilot-sha-or-current-validated-sha>^{commit} >/dev/null 2>&1 || git fetch --all --tags
git checkout <historical-pilot-sha-or-current-validated-sha>
git status --short --branch
git rev-parse HEAD
```

If the baseline SHA is already available locally and no update is needed, `git fetch --all --tags` is not required. If the SHA is missing locally or an update is needed, run the fetch before checkout.

Expected result:

- `git rev-parse HEAD` matches the SHA agreed for this validation run
- `detached HEAD` is acceptable after `git checkout <SHA>`
- the branch name does not have to match after checking out the exact SHA
- the working tree is clean or contains only pre-agreed doc-local changes

If the tree is dirty and the state is unexplained, the verdict cannot be higher than `partially_validated`.

## 3. Clean install in GPU mode

Use a fresh supported Linux VM whenever possible. If the host was already used for previous runs, clean the previous deployment in a controlled way first.

Recommended install path:

```bash
INSTALL_MODE=gpu ./install.sh
```

For this playbook:

- use the password login path as the baseline auth mode
- do not enable SSO unless a separate SSO validation track is being executed at the same time
- do not publish `.env`, JWT secrets, Redis/PostgreSQL passwords, keytab paths, or other secrets in reports or screenshots

Expected installer answers:

- supported AD / Kerberos / LDAP hostnames
- a valid test user for smoke checks, when available
- `SSO_ENABLED=false` if SSO is not in the same validation scope
- strong non-empty values for `REDIS_PASSWORD` and `SECRET_KEY`

After install, verify:

```bash
grep '^GPU_ENABLED=' .env
grep '^SSO_ENABLED=' .env
```

Expected result:

- `GPU_ENABLED=true`
- `SSO_ENABLED=false` when SSO is not part of this specific validation run

## 4. Stack checks

```bash
docker compose --profile gpu ps
docker compose --profile gpu config --services | grep -x worker-gpu
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

Expected result:

- `worker-gpu` exists and is running
- `health/live` and `health/ready` are healthy
- at least one working model is available
- the worker registry is not effectively empty

If the stack is healthy but `worker-gpu` is missing or unhealthy, the verdict cannot be higher than `partially_validated`.

## 5. Runtime checks

Run the following in the UI and record the result:

1. open `https://<host>/`
2. log in with a valid AD account through password login
3. run one normal chat request
4. run one file-chat request on a small `txt` or `pdf`
5. open `/admin/dashboard`

Keep this log view available in parallel:

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Expected result:

- login succeeds
- normal chat succeeds
- file-chat succeeds
- the dashboard opens and does not hide missing telemetry

## 6. GPU truth checks

### 6.1 Prove routing to GPU

While the chat request is running, inspect the logs:

```bash
docker compose logs --tail=300 app worker-chat worker-gpu scheduler | grep -E 'Routing job|target_kind|Skipping job'
```

Look for:

- explicit routing of a job to `gpu`
- absence of a pattern where all traffic silently falls back to CPU

### 6.2 Prove real GPU activity on the host

During a long-running chat request, run on the host:

```bash
nvidia-smi --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used --format=csv -l 1
```

You must see live activity that appears during the request and is not just the constant idle baseline.

If `worker-gpu` is running but host-side GPU activity is not confirmed, the verdict cannot be higher than `partially_validated`.

### 6.3 Check for silent CPU fallback

Temporarily stop the GPU worker:

```bash
docker compose stop worker-gpu
```

Then run one more normal chat request and verify that:

- the request either honestly falls back to CPU, or the behavior is explicitly reflected in the logs
- the dashboard does not pretend that the GPU is still healthy and active

After the check, restore the worker:

```bash
docker compose start worker-gpu
```

### 6.4 Check dashboard honesty for GPU telemetry

On `/admin/dashboard`, verify:

- the live GPU panel updates according to reality
- when telemetry is missing, `no-data` / `unavailable` is shown instead of synthetic zero/green success
- history/events do not create a false impression that GPU is already validated when the proof is missing

## 7. Final verdict criteria

### `validated`

All of the following are true at the same time:

- host preflight passed
- install in GPU mode completed successfully
- `worker-gpu` is healthy
- normal chat and file-chat passed
- log evidence shows routing to GPU
- host-side GPU activity evidence exists during a live request
- CPU fallback semantics were checked separately
- dashboard GPU telemetry behaves honestly

### `blocked_by_environment`

Any of the following:

- `nvidia-smi` does not work
- Docker cannot launch a GPU container
- host drivers/runtime are not ready

### `partially_validated`

For example:

- the stack started, but real GPU activity was not captured
- telemetry/dashboard coverage is incomplete
- `worker-gpu` is unstable

### `not_proven`

For example:

- the install effectively ran only in CPU semantics
- no GPU routing logs exist
- the only evidence is the presence of the `gpu` profile in Compose

## Acceptance note

Until the result is `validated`, GPU must not be included in the promised pilot scope as a proven capability.

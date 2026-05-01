# Live GPU Regression Plan

## Статус документа

Этот документ описывает план следующего live GPU validation window для текущего HEAD ветки `beta/gpu-model-validation` после Office file optimization v1.0 и parser quality gate.

Это не отчёт о выполненной проверке, не подтверждение результатов на GPU-стенде и не capacity benchmark. Цель окна - подтвердить demo / pilot validation readiness текущего regression baseline, а не провести production certification.

Source-of-truth VM для подготовки patches остаётся `SRV-AI` под пользователем `admin_ai` в репозитории `/home/admin_ai/ai_agent_v1.1`. Арендованный GPU host используется только как validation target и не становится source of truth.

## Цель validation window

Проверить на арендованном GPU host:

- clean deployment / install path на GPU host;
- hot model installer path и выбранный набор моделей;
- model pull и наличие моделей в runtime;
- `/health/live` и `/health/ready`;
- login/auth smoke;
- chat smoke;
- file-chat smoke;
- локальный parser quality gate после clone/pull;
- Office file optimization v1.0 на live runtime;
- cold start latency, warm response latency и file-chat latency;
- сбор artifact bundle без секретов.

## Требования к GPU host

Рекомендуемый baseline:

- Ubuntu `24.04.x`;
- 16 CPU;
- 128 GB RAM;
- NVIDIA RTX 4090 24 GB или эквивалентный GPU profile;
- Docker и Docker Compose;
- NVIDIA driver и `nvidia-container-toolkit`;
- доступ к GitHub, container registry и Ollama model pull endpoints;
- достаточно disk space для Docker images, Ollama models, logs и smoke artifacts;
- fresh host или заранее documented cleanup/factory reset для reused host.

CPU-only VM не подходит для этого validation window. VirtualBox TEST VM без GPU не подходит для GPU validation. `SRV-AI` является source of truth для репозитория и planning patches, но не validation host для этого окна.

## Branch / Commit Policy

- Validation выполнять из ветки `beta/gpu-model-validation`.
- Перед стартом зафиксировать exact HEAD, branch, дату, host и user.
- На validation host не делать локальных code changes.
- Если нужен fix, остановить validation, зафиксировать факт и вернуться на `SRV-AI` для patch.
- Validation host не является source of truth.
- Не делать `push` с validation host.
- Не менять `parser_stage.py`, runtime, installer, auth, tests, scripts или `models/catalog.json` в рамках validation window.

## Preflight Checks

Минимальная identity и host фиксация:

```bash
hostname
whoami
pwd
date -u
uname -a
cat /etc/os-release
lscpu
free -h
df -h
nvidia-smi
docker version
docker compose version
docker ps -a
docker volume ls
```

После clone или перехода в repo:

```bash
cd /home/admin_ai/ai_agent_v1.1
git status --short --branch
git rev-parse --short HEAD
git log --oneline --decorate -n 15
```

Готовый preflight script текущего smoke kit:

```bash
scripts/smoke/preflight_gpu_host.sh
```

Stop condition: если host не соответствует согласованному validation target, branch/head неверные, working tree dirty до install или GPU runtime не виден через `nvidia-smi`/Docker, heavy tests не запускать.

## Clean Install Strategy

Fresh host:

```bash
git clone <repo-url> /home/admin_ai/ai_agent_v1.1
cd /home/admin_ai/ai_agent_v1.1
git checkout beta/gpu-model-validation
git pull --ff-only
git status --short --branch
git rev-parse --short HEAD
```

Reused host:

- сначала выполнить controlled cleanup/factory reset по актуальному install/runbook path;
- сохранить cleanup notes в artifacts;
- не смешивать старый deploy с clean validation;
- перед install повторно проверить `docker ps -a`, `docker volume ls`, disk и repo state.

Install log обязателен:

```bash
mkdir -p artifacts/validation
set -o pipefail
date -u +%Y-%m-%dT%H:%M:%SZ | tee artifacts/validation/install-start.txt
INSTALL_MODE=gpu ./install.sh 2>&1 | tee artifacts/validation/install.log
date -u +%Y-%m-%dT%H:%M:%SZ | tee artifacts/validation/install-end.txt
```

Если rented lab не имеет AD/Kerberos/LDAP, допустимо явно выбрать documented standalone GPU lab path и зафиксировать это в отчёте. Это не заменяет отдельную real-infra auth validation.

## Модельный набор для validation

На текущем HEAD installer hot list берётся из `models/catalog.json`. Для regression window на RTX 4090 24 GB реалистичный primary set:

- `qwen3:8b` - основной file-chat candidate;
- `deepseek-r1:8b` - reasoning baseline;
- `gemma3:4b` - lightweight baseline;
- `llama3.1:8b` - interactive baseline.

Optional, если осталось время и primary regression уже прошёл:

- выбрать один 14B candidate: `qwen3:14b` или `deepseek-r1:14b`;
- не тянуть оба 14B в первое окно без отдельного решения.

Не включать `30B`/`32B`/`70B` модели в это regression window, если цель - regression, а не heavy benchmark.

Canonical default по installer catalog на текущем HEAD может оставаться `phi3:mini`; это не нужно менять в `models/catalog.json`. Для первого GPU regression window default model следует выбрать явно во время installer/model selection:

- `qwen3:8b` - рекомендуемый file-chat-focused default;
- `deepseek-r1:8b` - альтернативный reasoning-focused default.

Если нужен один default для первого окна, рекомендован `qwen3:8b`, потому что предыдущий GPU validation bundle показывал лучший file-chat result именно на этом кандидате. В отчёте нужно записать фактически выбранный `DEFAULT_MODEL` из `.env`.

## Проверки До Live Smoke

Локальный parser quality gate выполнить на validation host после clone/pull и до live smoke:

```bash
PYTHON=/tmp/ai-agent-test-venv/bin/python bash scripts/smoke/run_parser_quality_gate.sh
```

Extended gate optional:

```bash
RUN_INSTALLER_CONTRACT=1 PYTHON=/tmp/ai-agent-test-venv/bin/python bash scripts/smoke/run_parser_quality_gate.sh
```

Если venv/dependencies отсутствуют:

```bash
python3 -m venv /tmp/ai-agent-test-venv
/tmp/ai-agent-test-venv/bin/python -m pip install --upgrade pip
/tmp/ai-agent-test-venv/bin/python -m pip install -r requirements.txt
```

Parser quality gate является local deterministic check: он не стартует services, не вызывает LLM/Ollama и не требует GPU.

## Runtime Checks

После install и перед smoke:

```bash
docker compose --profile gpu ps
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
nvidia-smi
docker compose logs --tail=300 app worker-chat worker-gpu worker-parser scheduler ollama nginx
```

Во время cold/warm inference отдельно снять live GPU activity:

```bash
nvidia-smi --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used --format=csv -l 1
```

Проверить:

- stack healthy;
- `/health/live` возвращает ok;
- `/health/ready` возвращает ready;
- выбранные модели присутствуют в Ollama;
- default model отвечает;
- `worker-gpu` присутствует в GPU profile;
- `nvidia-smi` показывает GPU до и после inference;
- logs не содержат неожиданных 5xx, unhandled exceptions, model-not-found для выбранного default или parser crash.

## Smoke Checks

Перед smoke задать credentials без сохранения секретов в artifacts:

```bash
export SMOKE_BASE_URL=https://127.0.0.1
export SMOKE_USERNAME=<test-user>
export SMOKE_PASSWORD_FILE=/secure/path/to/smoke-user.secret
export SMOKE_INSECURE=1
```

Основной порядок:

```bash
scripts/smoke/check_runtime_ready.sh
scripts/smoke/run_full_smoke.sh
```

Если нужен отдельный rerun:

```bash
scripts/smoke/run_chat_smoke.sh
scripts/smoke/run_file_chat_smoke.sh
scripts/smoke/collect_metrics.sh --phase final
```

Не долбить login при HTTP `429`. Если получен `429`, сделать cooldown, зафиксировать событие как auth/rate-limit condition и не считать его model failure без повторной проверки после ожидания.

Smoke artifacts сохраняются в `artifacts/smoke/<timestamp>/`.

## File-Chat Regression Matrix

Обязательные success cases:

- TXT entities / parameters;
- text-layer PDF entities/table;
- DOCX with paragraph/table;
- DOCX headers/footers/comments/tracked changes synthetic case, если есть smoke fixture или manual upload;
- CSV simple table;
- XLSX sheets/rows/cells;
- XLSX formulas metadata;
- XLSX merged cells / hidden metadata;
- PNG OCR baseline;
- JPG OCR quick check, если есть fixture или manual test.

Expected controlled failures:

- scanned/image-only PDF -> explicit "PDF OCR not supported yet" / controlled no-text-layer message;
- malformed PDF -> controlled error;
- broken DOCX / missing `word/document.xml` -> controlled error;
- unsupported `.xls` -> unsupported / controlled error;
- oversized image -> controlled error.

Текущий `tests/smoke/specs/file_chat_cases.json` покрывает TXT, text-layer PDF, DOCX paragraph/table, PNG OCR и oversized image controlled failure. CSV, XLSX, scanned PDF, malformed PDF, broken DOCX, `.xls`, DOCX headers/footers/comments/tracked changes и JPG могут быть покрыты parser quality gate, gold corpus или manual validation, но не должны считаться fully automated live smoke coverage, если соответствующего smoke case нет в текущем HEAD.

Если live smoke suite ещё не покрывает все новые Office metadata cases, это фиксируется как manual/regression gap, а не как product failure.

## Metrics To Capture

Снять и сохранить:

- install duration;
- model pull duration per model, если возможно;
- model list and size;
- cold start latency first request per default model;
- warm response latency p50/p95 по chat smoke;
- file-chat latency p50/p95;
- parser failures count;
- queue depth / active jobs;
- `/health/ready` payload;
- GPU memory usage during inference;
- CPU/RAM/disk usage snapshot;
- failed/rejected jobs metrics;
- HTTP `429` events;
- OCR/file parser controlled failure counts.

Metrics are validation-window measurements, not production capacity planning.

## Artifact Bundle Requirements

Сохранить:

- `git_and_identity.txt`;
- `env_safe.txt` без секретов;
- `docker_ps.txt`;
- `docker_ps_a.txt`;
- `docker_volume_ls.txt`;
- `health_live.json`;
- `health_ready.json`;
- `nvidia_smi.txt`;
- `ollama_list.txt`;
- `ollama_ps.txt`;
- install logs;
- smoke artifacts;
- docker logs;
- parser quality gate output;
- model selection summary;
- cleanup notes, если host reused.

Не сохранять secret values, bootstrap secret contents, `.env` целиком, passwords, tokens, keytabs или cookie jars за пределами smoke artifact rules.

На текущем HEAD отдельный universal bundle script не зафиксирован в docs/scripts audit. Базовый сбор обеспечивают `scripts/smoke/preflight_gpu_host.sh`, `scripts/smoke/check_runtime_ready.sh`, `scripts/smoke/run_full_smoke.sh` и `scripts/smoke/collect_metrics.sh`; недостающие файлы из списка выше сохранить вручную в validation artifacts.

## PASS / FAIL Criteria

Installer/runtime PASS:

- clean install завершился;
- stack healthy;
- `/health/live` ok;
- `/health/ready` ready;
- selected models present in Ollama;
- default model responds;
- chat smoke PASS;
- parser quality gate PASS.

File-chat PASS:

- core TXT/PDF/DOCX/CSV/XLSX cases PASS;
- expected negative cases fail controlled;
- OCR image case PASS либо documented OCR issue без masking regression;
- нет неожиданных 5xx в `app`/`nginx` logs.

DEGRADED:

- runtime healthy и chat работает, но file-chat имеет известную OCR quality issue;
- smoke blocked by login `429`, но manual auth работает после cooldown;
- one non-critical model pull failed, но primary default работает.

FAIL:

- install fails;
- stack not healthy;
- `/health/ready` not ready;
- selected default model missing;
- chat smoke cannot run after cooldown;
- parser quality gate fails;
- uncontrolled parser crash / unhandled exception;
- secrets exposed in artifacts.

## Rollback / Cleanup Rules

Если validation run нужно остановить или откатить:

- сначала сохранить artifacts и notes по причине остановки;
- не править code/scripts/tests на validation host;
- не маскировать failed state повторным install без отдельной записи в отчёте;
- для cleanup использовать documented install/runbook path, а не ручное удаление неизвестных state files;
- после cleanup зафиксировать `docker ps -a`, `docker volume ls`, disk snapshot и repo state;
- все fixes выполнять отдельным patch на `SRV-AI`, затем начинать новый validation run с новым exact HEAD.

## Stop Rules

Остановиться и не продолжать heavy tests, если:

- wrong host или не тот validation target;
- wrong branch/head;
- dirty working tree на validation host до install;
- GPU runtime не detected;
- Docker stack unstable;
- `/health/ready` not ready;
- secrets accidentally printed;
- test начинает менять code на validation host.

## Что Не Трогаем В Этом Validation Window

- не разрабатываем PDF OCR;
- не разрабатываем comparison engine;
- не расширяем installer;
- не меняем model catalog;
- не правим production code на validation host;
- не benchmark `30B`/`32B`/`70B` без отдельного approval;
- не делаем SOC/SIEM integration;
- не заявляем production capacity.

## Report Format

Финальный report после validation window должен содержать:

```text
Host facts:
Repo/commit:
Install result:
Selected models:
Health result:
Chat smoke:
File-chat smoke:
Parser quality gate:
Metrics summary:
Artifacts path:
Issues:
Verdict: PASS | DEGRADED | FAIL
Next one action:
```

В `Next one action` указать ровно один следующий шаг. После regression plan и validation readiness decision следующий крупный feature-блок выбирается отдельно: PDF OCR или comparison engine, но не оба одновременно.

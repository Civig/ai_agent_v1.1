# Плейбук валидации GPU

## Назначение

Этот playbook нужен для отдельной проверки GPU path на dedicated GPU host. Пока этот сценарий не выполнен, GPU не считается доказанной capability пилота.

## Классы итогового вердикта

- `validated` - GPU path доказан end-to-end
- `blocked_by_environment` - проверка заблокирована драйверами, runtime или host preparation
- `partially_validated` - часть сценария пройдена, но реальное GPU use или telemetry honesty не доказаны полностью
- `not_proven` - stack мог подняться, но GPU capability не доказана

## 1. Предварительная проверка хоста

Выполнить на целевом GPU host:

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

Если внешний pull в вашем контуре ограничен, используйте заранее одобренный и доступный локально CUDA utility image с эквивалентной проверкой `nvidia-smi`.

Ожидаемый результат:

- GPU определяется на хосте
- `nvidia-smi` работает без ошибок
- Docker видит GPU runtime и способен запустить test container с `--gpus all`

Если любой из этих пунктов не проходит, verdict сразу `blocked_by_environment`.

## 2. Фиксация репозитория и чистое состояние дерева

```bash
cd /home/admin_ai/ai_agent_v1.1
git rev-parse --verify 33960581772787b162a0885bc2181f650f22a168^{commit} >/dev/null 2>&1 || git fetch --all --tags
git checkout 33960581772787b162a0885bc2181f650f22a168
git status --short --branch
git rev-parse HEAD
```

Если baseline SHA уже есть локально и update не нужен, `git fetch --all --tags` не требуется. Если SHA отсутствует локально или нужно подтянуть update, выполняется `fetch` перед `checkout`.

Ожидаемый результат:

- `git rev-parse HEAD` совпадает с baseline SHA
- после `git checkout <SHA>` допустим `detached HEAD`
- имя branch после точного `checkout` SHA совпадать не обязано
- working tree clean или содержит только заранее согласованные doc-local changes

Если tree грязный и состояние не объяснено, verdict не выше `partially_validated`.

## 3. Чистая установка в GPU mode

Предпочтительно использовать fresh supported Linux VM. Если хост уже использовался для предыдущих прогонов, сначала очистить предыдущий deployment согласованным способом.

Рекомендуемый install path:

```bash
INSTALL_MODE=gpu ./install.sh
```

Для этого playbook:

- использовать password login path как baseline auth mode
- не включать SSO, если одновременно не выполняется отдельный SSO validation track
- не публиковать `.env`, JWT secret, Redis/PostgreSQL passwords, keytab paths и другие секреты в отчётах или скриншотах

Ожидаемые installer answers:

- supported AD / Kerberos / LDAP hostnames
- валидный test user для smoke check, если доступен
- `SSO_ENABLED=false`, если нет отдельного SSO validation scope
- сильные непустые значения для `REDIS_PASSWORD` и `SECRET_KEY`

После install проверить:

```bash
grep '^GPU_ENABLED=' .env
grep '^SSO_ENABLED=' .env
```

Ожидаемый результат:

- `GPU_ENABLED=true`
- `SSO_ENABLED=false`, если SSO не входит в этот конкретный validation run

## 4. Проверка стека

```bash
docker compose --profile gpu ps
docker compose --profile gpu config --services | grep -x worker-gpu
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

Ожидаемый результат:

- `worker-gpu` существует и запущен
- `health/live` и `health/ready` healthy
- есть хотя бы одна рабочая модель
- worker registry не выглядит пустым

Если stack healthy, но `worker-gpu` отсутствует или unhealthy, verdict не выше `partially_validated`.

## 5. Проверка работы системы

Выполнить в UI и зафиксировать результат:

1. открыть `https://<host>/`
2. войти под валидным AD account через password login
3. выполнить один обычный chat request
4. выполнить один file-chat request на небольшом `txt` или `pdf`
5. открыть `/admin/dashboard`

Параллельно держать под рукой:

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Ожидаемый результат:

- login успешен
- normal chat успешен
- file-chat успешен
- dashboard открывается и не скрывает missing telemetry

## 6. Проверки реальности GPU

### 6.1 Доказать маршрутизацию на GPU

Во время chat request проверить логи:

```bash
docker compose logs --tail=300 app worker-chat worker-gpu scheduler | grep -E 'Routing job|target_kind|Skipping job'
```

Ищем:

- явное направление job на `gpu`
- отсутствие картины, где весь трафик silently ушёл на CPU

### 6.2 Доказать реальную работу GPU на хосте

Во время длительного chat request выполнить на хосте:

```bash
nvidia-smi --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used --format=csv -l 1
```

Нужно увидеть live activity, которая появляется во время запроса и не сводится к постоянному idle baseline.

Если `worker-gpu` запущен, но host-side GPU activity не подтверждается, verdict не выше `partially_validated`.

### 6.3 Проверить отсутствие тихого CPU fallback

Временно остановить GPU worker:

```bash
docker compose stop worker-gpu
```

Затем выполнить ещё один обычный chat request и проверить, что:

- запрос либо честно уходит в CPU fallback, либо поведение явно отражено в логах
- dashboard не притворяется, что GPU still healthy and active

После проверки вернуть worker:

```bash
docker compose start worker-gpu
```

### 6.4 Проверить честность GPU-телеметрии в dashboard

На `/admin/dashboard` проверить:

- live GPU panel обновляется в соответствии с реальностью
- при отсутствии telemetry виден `no-data` / `unavailable`, а не synthetic zero/green success
- history/events не создают ложного впечатления, что GPU уже validated, если доказательств нет

## 7. Критерии итогового вердикта

### `validated`

Все условия ниже выполнены одновременно:

- host preflight прошёл
- install в GPU mode завершился успешно
- `worker-gpu` healthy
- normal chat и file-chat прошли
- есть log evidence маршрутизации на GPU
- есть host-side GPU activity evidence во время запроса
- CPU fallback semantics отдельно проверены
- dashboard GPU telemetry ведёт себя честно

### `blocked_by_environment`

Любой из пунктов ниже:

- `nvidia-smi` не работает
- Docker не запускает GPU container
- host drivers/runtime не готовы

### `partially_validated`

Например:

- stack поднялся, но real GPU activity не зафиксирована
- telemetry/dashboard часть неполна
- `worker-gpu` нестабилен

### `not_proven`

Например:

- install прошёл только в CPU semantics
- логов GPU routing нет
- evidence сводится только к наличию профиля `gpu` в Compose

## Примечание по приёмке

Пока итог не `validated`, GPU нельзя включать в обещанный pilot scope как уже доказанную capability.

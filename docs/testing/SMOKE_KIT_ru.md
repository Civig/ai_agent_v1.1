# Smoke/Load Testing Kit

Этот каталог добавляет воспроизводимый набор проверок для нового GPU-хоста после развёртывания Corporate AI Assistant. Kit не делает deploy/redeploy, не меняет runtime и не использует cloud endpoints.

## Состав

- `tests/smoke/fixtures/` — маленькие прозрачные TXT/PDF/DOCX/PNG фикстуры.
- `tests/smoke/specs/chat_cases.json` — обычные chat smoke-кейсы.
- `tests/smoke/specs/file_chat_cases.json` — file-chat кейсы с `must_contain`, `must_not_contain`, `expected_status`.
- `tests/smoke/specs/load_profiles.json` — профили `light`, `medium`, `warm_cold`.
- `scripts/smoke/` — preflight, runtime readiness, chat/file-chat smoke, metrics collection, full orchestration.
- `scripts/load/` — лёгкий live load для chat и file-chat плюс summarizer.

## Фикстуры

TXT:
- `entities.txt` — список сущностей `ALPHA-17`, `BRAVO-42`, `CHARLIE-09`.
- `parameters_table.txt` — таблицеподобные параметры.
- `missing_fields.txt` — частичная запись с отсутствующими полями.

PDF:
- `entity_report.pdf`
- `parameter_table.pdf`
- `monthly_metrics.pdf`
- `mixed_3p_report.pdf`

DOCX:
- `table_and_paragraphs.docx`
- `mixed_content.docx`

Images/OCR:
- `ocr_success.png` — маленькое изображение для успешного OCR.
- `oversized_dimension.png` — маленький по байтам PNG с размерностью `2201x2201`, ожидаемая controlled parse failure по dimension-limit.

Перегенерация:

```bash
python3 scripts/smoke/generate_fixtures.py
```

## Credentials

Для chat/file-chat нужен обычный password login приложения. Local break-glass bootstrap secret относится к dashboard-only access и не заменяет AD/test-user login для `/api/chat`.

Перед запуском задайте:

```bash
export SMOKE_BASE_URL=https://127.0.0.1
export SMOKE_USERNAME=aitest
export SMOKE_PASSWORD_FILE=/secure/path/to/smoke-user.secret
export SMOKE_INSECURE=1
```

Можно использовать `SMOKE_PASSWORD` вместо `SMOKE_PASSWORD_FILE`, но файл предпочтительнее. Секреты не сохраняются в artifacts.

## Smoke

Preflight:

```bash
scripts/smoke/preflight_gpu_host.sh
```

Runtime readiness:

```bash
scripts/smoke/check_runtime_ready.sh
```

Chat smoke:

```bash
scripts/smoke/run_chat_smoke.sh
```

File-chat smoke:

```bash
scripts/smoke/run_file_chat_smoke.sh
```

Полный прогон:

```bash
scripts/smoke/run_full_smoke.sh
```

Артефакты пишутся в `artifacts/smoke/<timestamp>/`.

## Load

Chat light:

```bash
python3 scripts/load/run_chat_load.py --host https://127.0.0.1 --profile light --insecure
```

Chat medium:

```bash
python3 scripts/load/run_chat_load.py --host https://127.0.0.1 --profile medium --insecure
```

File-chat light:

```bash
python3 scripts/load/run_file_chat_load.py --host https://127.0.0.1 --profile light --insecure
```

Summary для уже готового run:

```bash
python3 scripts/load/summarize_load_results.py --input-dir artifacts/load/<run>
```

Артефакты load пишутся в `artifacts/load/<timestamp>/`: `results.jsonl`, `results.csv`, `summary.json`, `raw_sse/`, `events/`.

## Метрики и логи

`scripts/smoke/collect_metrics.sh` собирает:

- `docker compose ps`, `docker ps -a`
- `nvidia-smi`
- `ollama ps`
- logs: `app`, `worker-gpu`, `worker-parser`, `scheduler`, `worker-chat`, `ollama`, `nginx`
- observability CSV/JSONL из строк `job_terminal_observability`, `file_parse_observability`, `job_queue_observability`

Ключевые поля:

- `pending_wait_ms` — ожидание до admission, если runtime начнёт логировать split wait. В текущем baseline collector заполняет его из `queue_wait_ms`, когда отдельного поля нет.
- `admitted_wait_ms` — ожидание после admission до worker start, если runtime логирует это поле. В текущем baseline может быть пустым.
- `queue_wait_ms` — фактический wait между enqueue и worker start.
- `inference_ms` — время генерации модели.
- `total_job_ms` / `total_ms` — полный terminal job duration.
- `parse_ms` — parser/OCR/document extraction duration.
- `doc_chars` — число символов документа после budget/trimming.

## Как отличать типы проблем

Parser issue:
- file-chat падает, обычный chat проходит;
- в логах есть `file_parse_observability terminal_status=failed`;
- растёт `parse_ms` или ошибка похожа на `parse_error`, `validation_error`, OCR/PDF/DOCX limit.

Queue issue:
- `/health/ready` degraded или показывает backlog/active jobs;
- `job_queue_observability` есть, но terminal lines приходят поздно;
- `queue_wait_ms`/`pending_wait_ms` растут, а `inference_ms` нормальный.

Model/runtime issue:
- `/api/models` пустой или возвращает ошибку;
- chat и file-chat оба не проходят;
- `job_terminal_observability terminal_status=failed` с `model_not_found`, `inference_timeout`, `runtime_unavailable`;
- `ollama ps` пустой при ожидаемой модели или `nvidia-smi` не видит GPU.

## Примечания

- `medium` профиль намеренно маленький: 3 concurrent workers и 9 chat requests. Это smoke-load, не capacity benchmark.
- Для честного multi-user benchmark используйте отдельный существующий контур `tests/load_benchmark/`.
- `artifacts/` игнорируется git и предназначен только для runtime evidence.

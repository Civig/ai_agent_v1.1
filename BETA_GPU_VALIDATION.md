# Beta GPU Model Validation

Эта ветка предназначена только для pre-enterprise GPU validation.

## Назначение
Используется для:
- выбора подходящей LLM-модели перед enterprise rollout
- проверки GPU runtime
- проверки latency и concurrency
- проверки parser/document workflows
- проверки сценариев генерации таблиц и Excel-структур

## Installer contract
Ветка должна поддерживать упрощённый GPU-lab flow:
- installer спрашивает только модель
- автоматически включает standalone GPU-lab профиль
- автоматически создаёт 2 bootstrap users:
  - frontend test user
  - dashboard admin
- автоматически настраивает GPU override для ollama

## Auth contract
- frontend test user: локальный hash-only login
- dashboard admin: отдельный dashboard-only path
- без зависимости frontend test user от AD-group model policies
- frontend test user получает доступ к installer-selected model(s)

## Ограничения
- это не production-ветка
- не использовать как enterprise runtime
- после validation стенд должен сноситься
- для enterprise deployment использовать main на чистой среде

## Обязательные тесты
- chat smoke test
- concurrent requests: 5 / 10 / 15
- latency measurement
- parser/document tests
- table / Excel-related workflows

## Статус paid GPU validation audit

Зафиксировано `2026-05-06` по summary оплаченного GPU validation audit.

### Факты validation target

- Арендованный GPU host: `testai`
- Наблюдаемая ОС: Ubuntu `24.04.4 LTS`
- GPU: RTX 4090
- NVIDIA driver: `595.58.03`
- CUDA: `13.2`
- Ветка во время validation: `beta/gpu-model-validation`
- GPU validation audit baseline: около commit `08c183a`
- Последующий fix load harness уже отправлен: `76ca0cd test(load): reuse authenticated smoke sessions`

### Runtime результат

- Install завершился успешно.
- Docker Compose stack стал healthy.
- `/health/live` вернул `ok`.
- `/health/ready` вернул `ready`.
- Ollama видел GPU и запускал `deepseek-r1:8b` на 100% GPU.
- Модели, присутствовавшие во время validation:
  - `deepseek-r1:8b`
  - `deepseek-r1:14b`
  - `qwen3:8b`
  - `qwen3:14b`
  - `gemma3:4b`
  - `llama3.1:8b`

### Quality gates и smoke

- Parser quality gate прошёл.
- Comparison quality gate прошёл.
- Chat smoke прошёл `3/3`.
- Последний file-chat smoke: `9/12`.
- Основные file-chat misses были в основном LLM/evaluator brittleness:
  - `pdf_list_entities`: parser извлёк `ALPHA-17` / `BRAVO-42` / `CHARLIE-09`, но LLM перевёл или изменил формат.
  - `docx_table_and_paragraphs`: parser содержал `Project Helios`, но LLM ответил `Helios`.
  - `txt_missing_budget_question` был нестабилен, семантически приемлем и позднее прошёл.
- Реальный OCR quality gap:
  - `image_ocr_success` direct parser извлёк `ALPHA-1? SCORE 36` вместо ожидаемых значений.
- Expected negative test:
  - oversized image `2201x2201` был корректно отклонён из-за `2000px` dimension limit.

### Initial load result

- `chat/light` прошёл: `3/3`, p50 около `2692 ms`, p95 около `3691.9 ms`.
- `chat/medium` прошёл: `9/9`, p50 около `6359 ms`, p95 около `9383.8 ms`.
- `chat/warm_cold` и file-chat load profiles были заблокированы `login_failed_http_429`.
- Root cause для `429`:
  - load scripts логинились per worker/profile;
  - production login limiter работал as designed.
- Fix уже implemented and pushed:
  - `76ca0cd test(load): reuse authenticated smoke sessions`
  - изменил только load/smoke harness behavior;
  - не ослабил production login rate limiter или runtime security.

### Текущий вывод

- GPU install/runtime proof успешен.
- Parser и comparison local quality gates прошли на validation track.
- Chat smoke и initial chat load успешны.
- File-chat всё ещё имеет known LLM/evaluator brittleness и реальный OCR quality gap.
- Production capacity ещё не подтверждена.
- Не заявлять поддержку `1000` пользователей на основании этой validation.

## Checklist следующего GPU validation window

Следующее rented GPU window должно стартовать с current branch и включать:

1. Preflight host, GPU, driver, Docker и Compose.
2. Подтвердить branch и exact commit.
3. Подтвердить install/runtime health.
4. Запустить parser quality gate.
5. Запустить comparison quality gate.
6. Запустить full smoke.
7. Повторить load profiles после `76ca0cd`:
   - подтвердить, что `chat/warm_cold` больше не падает на login `429`;
   - подтвердить, что file-chat `light`, `medium` и `warm_cold` больше не падают на login `429`;
   - подтвердить, что `results.jsonl` и `summary.json` создаются для каждого profile.
8. Собрать final artifacts.
9. Проверить отсутствие secrets в bundle.
10. Только после этого остановить арендованный GPU host.

## Следующая работа без GPU

- Синхронизировать docs/status с paid GPU audit.
- Harden non-GPU smoke/evaluator expectations там, где wording LLM вызывает brittle failures.
- Вести OCR quality gap отдельно; не считать его исправленным load harness changes.
- Не запускать live GPU smoke/load до следующего approved rented GPU window.

## Итог
Эта ветка нужна для выбора модели и валидации GPU-сценария до перехода на production main. На текущем audit status GPU install/runtime proof успешен, но production capacity ещё не доказана.

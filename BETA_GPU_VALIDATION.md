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

## Итог
Эта ветка нужна для выбора модели и валидации GPU-сценария до перехода на production main.

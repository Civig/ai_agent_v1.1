# Пилотный регламент

## Назначение

Этот runbook нужен для pilot handoff и первых operator checks после установки.

## Основные URL

- основное приложение: `https://<host>/`
- liveness: `https://<host>/health/live`
- readiness: `https://<host>/health/ready`
- operator dashboard: `https://<host>/admin/dashboard`

## 5-минутная проверка после установки

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

Ожидаемый baseline:

- stack поднят
- `health/ready` healthy
- есть хотя бы одна модель
- scheduler heartbeat свежий
- есть хотя бы один chat-capable worker

## Быстрый smoke-тест

1. открыть `https://<host>/`
2. войти под валидным AD account через password login
3. отправить один обычный chat request
4. отправить один file-chat request с небольшим поддерживаемым файлом
5. открыть `/admin/dashboard`

## Как понять, что система в порядке

Система считается в нормальном состоянии, если:

- readiness зелёный
- login работает
- normal chat и file-chat завершаются без unexpected errors
- dashboard summary/live/history/events открываются
- queue после smoke test возвращается к idle или near-idle состоянию
- dashboard честно показывает `no-data` / `unavailable`, если метрики временно недоступны

## Первые команды при проблемах

Основные логи:

```bash
docker compose logs --tail=200 app scheduler worker-chat nginx
docker compose logs --tail=200 app worker-parser worker-chat
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Проверки моделей и очередей:

```bash
docker compose exec -T ollama ollama list
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p0 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p1 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p2'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
```

## Первая реакция на типовые проблемы

### Не работает вход

- проверить DNS/LDAP/KDC hostname resolution
- посмотреть `app` logs
- если проверяется SSO, помнить, что это отдельный validation track, а не baseline assumption

### Не работает чат

- проверить `ollama list`
- посмотреть `app`, `worker-chat`, `scheduler`
- убедиться, что доступна выбранная модель

### Не работает чат с файлами

- посмотреть `app` и `worker-parser` logs
- проверить тип файла и лимиты
- искать `file_parse_observability`, `upload_rejected`, `error_type`

### Панель оператора выглядит пустой

- сначала сравнить с `health/ready`, worker heartbeat и queue state
- помнить, что честное `no-data` / `unavailable` не равно поломке UI

### GPU-пилот деградировал

- проверить [GPU_VALIDATION_PLAYBOOK_ru.md](GPU_VALIDATION_PLAYBOOK_ru.md)
- искать routing logs и host-side `nvidia-smi` evidence
- не считать наличие `worker-gpu` достаточным доказательством

## Команды безопасной очистки

```bash
bash uninstall.sh --dry-run
sudo bash uninstall.sh --dry-run --factory-reset
```

`factory-reset` использовать только когда нужен manifest-scoped rollback installer-owned host changes.

## Связанные документы

- [PILOT_ACCEPTANCE_CHECKLIST_ru.md](PILOT_ACCEPTANCE_CHECKLIST_ru.md)
- [PILOT_LIMITATIONS_ru.md](PILOT_LIMITATIONS_ru.md)
- [ADMIN_ru.md](ADMIN_ru.md)
- [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md)

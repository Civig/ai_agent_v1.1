# Администрирование и эксплуатация

## Область действия

Этот документ описывает day-2 эксплуатацию Corporate AI Assistant. Он опирается на текущую реализацию репозитория и текущую модель развёртывания через Docker Compose.

## Состав сервисов

Базовый stack:

- `corporate-ai-nginx`
- `corporate-ai-assistant`
- `corporate-ai-scheduler`
- `corporate-ai-worker-chat`
- `corporate-ai-worker-siem`
- `corporate-ai-worker-batch`
- `corporate-ai-redis`
- `ollama-server`

Опционально:

- `corporate-ai-worker-gpu`

## Базовые lifecycle-команды

### Запуск stack

```bash
docker compose up -d
```

### Пересборка и рестарт

```bash
docker compose up -d --build
```

### Запуск с optional GPU worker

```bash
docker compose --profile gpu up -d
```

### Остановка stack

```bash
docker compose down
```

### Состояние контейнеров

```bash
docker compose ps
```

## Логи

### Follow основных сервисов

```bash
docker compose logs -f app scheduler worker-chat nginx
```

### Диагностика file-processing behavior

```bash
docker compose logs --tail=200 app worker-chat
```

### Диагностика GPU-related runtime behavior

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Полезные log markers, которые сейчас реально есть в коде:

- `Routing job ... to cpu|gpu`
- `file_parse_observability`
- `job_queue_observability`
- `job_terminal_observability`
- `upload_rejected`
- `Skipping job ... because target_kind mismatch`

## Health checks

### HTTP health endpoints

```bash
curl -k -i https://127.0.0.1/health/live
curl -k -i https://127.0.0.1/health/ready
curl -k -i https://127.0.0.1/health
```

### Что означает readiness сейчас

`/health/ready` возвращает успех только когда:

- доступен Redis
- heartbeat scheduler свежий
- работает хотя бы один chat-capable worker
- runtime сообщает, что есть schedulable chat capacity

### Health контейнеров

```bash
docker compose ps
```

Compose health checks используют `runtime_healthcheck.py` для `app`, `scheduler` и worker'ов.

## Работа с моделями

### Показать модели

```bash
docker compose exec -T ollama ollama list
```

### Подтянуть модель вручную

```bash
docker compose exec -T ollama ollama pull phi3:mini
docker compose exec -T ollama ollama pull gemma2:2b
```

### Выполнить repository bootstrap logic

```bash
./bootstrap_ollama_models.sh
```

Если моделей нет, stack может быть поднят, но chat requests всё равно будут падать.

## Проверка queue и job lifecycle

### Проверить scheduler heartbeat

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
```

### Проверить зарегистрированные worker'ы

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### Проверить pending queues

Пример для chat priority queues:

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p0 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p1 && redis-cli -a "$REDIS_PASSWORD" LLEN llm:queue:chat:p2'
```

### Посмотреть конкретную job

```bash
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:job:<job_id>'
```

### Что смотреть в логах

- `job_queue_observability` для queue wait time
- `job_terminal_observability` для terminal status, inference time и total job time
- routing logs для CPU/GPU target selection

## File upload, PDF и OCR

### Поддерживаемые upload types

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### Базовые проверки file processing

```bash
docker compose logs --tail=200 app
```

Ищите:

- `file_parse_observability`
- `upload_rejected`
- логи принятия file-chat request

### Примечания по PDF path

PDF path — часть текущего backend implementation. Если PDF extraction перестала работать после drift окружения, пересоберите application image:

```bash
docker compose up -d --build app worker-chat worker-siem worker-batch
```

### Примечания по OCR path

OCR сейчас встроен в container image для поддерживаемых image uploads. Если image extraction не работает, сначала проверяйте `app` logs, а не предполагайте logic regression.

## Observability logs

Сейчас в репозитории observability реализована как baseline через structured logs, а не через внешний telemetry stack.

Ключевые поля, которые сейчас доступны:

- parse timing
- queue wait timing
- inference timing
- total job timing
- model key / model name
- workload class
- target kind
- terminal status
- нормализованный `error_type`

Какие события удобно grep'ать:

```bash
docker compose logs --tail=300 app worker-chat scheduler | grep -E 'file_parse_observability|job_queue_observability|job_terminal_observability|upload_rejected|Routing job'
```

## Регулярное обслуживание

Рекомендуемые регулярные проверки:

- `docker compose ps`
- `/health/ready`
- `docker compose exec -T ollama ollama list`
- использование диска Redis и Ollama volumes
- срок действия TLS certificate
- ротация секретов `.env` по внутренней политике

После изменений моделей или инфраструктуры рекомендуется:

- пересобрать затронутые сервисы
- выполнить login smoke test
- выполнить один обычный SSE chat request
- выполнить один file-chat request
- убедиться, что после этого `/health/ready` снова healthy

## Post-update smoke test

Минимальный smoke test после обновления:

1. `docker compose up -d --build`
2. `docker compose ps`
3. `curl -k https://127.0.0.1/health/ready`
4. войти под валидным AD account
5. отправить один обычный chat request
6. отправить один file-chat request с маленьким текстовым или PDF файлом
7. убедиться, что очередь возвращается в idle

## Реакция на деградацию

### Если деградировал `/health/ready`

- проверьте логи `app`, `scheduler`, `worker-chat`, `redis`, `ollama`
- проверьте, доступны ли модели
- проверьте heartbeat scheduler
- проверьте heartbeat хотя бы одного worker'а

### Если растёт queue latency

- смотрите `job_queue_observability`
- проверьте, healthy ли worker'ы
- проверьте, существует ли выбранная модель
- убедитесь, что GPU routing не ждёт недоступный GPU worker

### Если деградировал file chat

- смотрите `file_parse_observability`
- смотрите `upload_rejected`
- убедитесь, что тип и размер файла поддерживаются
- проверьте worker terminal logs и `error_type`

## Rollback basics

Отдельной release-management system в репозитории нет. Практический rollback path выглядит так:

1. восстановить на хосте предыдущую known-good revision репозитория
2. сохранить или вернуть соответствующий `.env`
3. пересобрать stack:

```bash
docker compose up -d --build
```

Если в rollout менялись модели, после rollback также проверьте доступный набор Ollama models.

## Связанные документы

- [Install Guide](INSTALL_ru.md)
- [Архитектура](ARCHITECTURE_ru.md)
- [Troubleshooting](TROUBLESHOOTING_ru.md)
- [Базовый security baseline](SECURITY_ru.md)
- [README.md](../README.md)

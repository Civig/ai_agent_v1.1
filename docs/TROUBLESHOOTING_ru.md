# Troubleshooting

## Область действия

Этот документ описывает типовые deployment- и runtime-проблемы Corporate AI Assistant в его текущей Docker Compose форме.

Базовые первые проверки почти для любой проблемы:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat nginx
curl -k -i https://127.0.0.1/health/live
curl -k -i https://127.0.0.1/health/ready
```

## Ошибка логина или Kerberos issue

### Симптом

- страница логина открывается, но вход не проходит
- в `app` logs появляются ошибки LDAP/Kerberos
- видны ошибки типа `No worthy mechs found` или ошибки directory lookup

### Вероятная причина

- неверные LDAP/Kerberos settings в `.env`
- hostname/SPN mismatch
- отсутствует или некорректен `deploy/krb5.conf`
- проблема сетевой доступности AD/KDC

### Как проверить

```bash
docker compose logs --tail=200 app
docker compose exec -T app bash -lc 'cat /etc/krb5.conf'
docker compose exec -T app bash -lc 'getent hosts <ldap-hostname>'
```

Если возможно, запустите repository auth diagnostic:

```bash
AUTH_CHECK_PASSWORD='***' ./diagnose_auth_runtime.sh <username>
```

### Как исправить

- проверьте LDAP/Kerberos значения в `.env`
- проверьте, что LDAP hostname резолвится внутри контейнеров
- убедитесь, что runtime hostname соответствует ожиданиям AD SPN
- пересоздайте или исправьте `deploy/krb5.conf`

## `/health/ready` не healthy

### Симптом

- `/health/ready` возвращает `503`
- `docker compose ps` показывает unhealthy services

### Вероятная причина

- недоступен Redis
- heartbeat scheduler отсутствует или устарел
- нет working chat worker
- проблемы с Ollama или с доступностью моделей

### Как проверить

```bash
docker compose ps
docker compose logs --tail=200 redis scheduler worker-chat ollama app
curl -k -i https://127.0.0.1/health/ready
```

### Как исправить

- сначала восстановите упавший контейнер
- убедитесь, что healthy хотя бы один chat worker
- убедитесь, что в Ollama есть хотя бы одна модель
- пересоберите затронутые сервисы, если есть runtime drift

## Model not found

### Симптом

- chat requests падают, хотя stack поднят
- список моделей в UI пустой или неполный

### Вероятная причина

- ни одна модель Ollama не установлена
- выбранная модель отсутствует в runtime

### Как проверить

```bash
docker compose exec -T ollama ollama list
docker compose logs --tail=100 app worker-chat
```

### Как исправить

```bash
docker compose exec -T ollama ollama pull phi3:mini
./bootstrap_ollama_models.sh
```

## File upload rejected

### Симптом

- upload возвращает `400`
- file-chat request отклоняется ещё до inference

### Вероятная причина

- неподдерживаемое расширение
- content-type mismatch
- слишком большой файл
- слишком много файлов в одном запросе

### Как проверить

```bash
docker compose logs --tail=200 app | grep upload_rejected
```

### Как исправить

- используйте поддерживаемый тип: `txt`, `pdf`, `docx`, `png`, `jpg`, `jpeg`
- убедитесь, что browser/content-type соответствует расширению
- уменьшите размер файла или число файлов

## Проблема с PDF parsing

### Симптом

- PDF upload принимается, но file chat завершается ошибкой
- в `app` logs видно PDF parser-related failure

### Вероятная причина

- drift application image
- поломанное состояние runtime dependencies
- повреждённый или сложный PDF

### Как проверить

```bash
docker compose logs --tail=200 app
```

Ищите ошибки file-parse рядом с PDF requests.

### Как исправить

```bash
docker compose up -d --build app worker-chat worker-siem worker-batch
```

Если проблема связана с конкретным файлом, сначала протестируйте более простой PDF.

## Очередь зависла или job не завершается

### Симптом

- chat остаётся в queued
- terminal status не достигается
- `/health/ready` может одновременно быть degraded

### Вероятная причина

- отсутствует scheduler heartbeat
- нет worker capacity
- отсутствует модель
- mismatch worker/target

### Как проверить

```bash
docker compose logs --tail=200 scheduler worker-chat app
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" GET llm:scheduler:heartbeat'
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### Как исправить

- восстановите health scheduler и worker'ов
- проверьте доступность моделей
- смотрите `job_queue_observability` и `job_terminal_observability`
- проверьте routing logs на проблемы CPU/GPU target assignment

## Worker не обрабатывает jobs

### Симптом

- pending jobs есть, но `worker-chat` их не обрабатывает

### Вероятная причина

- worker container unhealthy
- heartbeat worker'а отсутствует или устарел
- target mismatch

### Как проверить

```bash
docker compose ps
docker compose logs --tail=200 worker-chat scheduler
docker compose exec -T redis sh -lc 'redis-cli -a "$REDIS_PASSWORD" SMEMBERS llm:workers'
```

### Как исправить

- перезапустите или пересоберите worker
- убедитесь, что `worker-chat` healthy
- если включён GPU routing, проверьте, что запрошенный `target_kind` соответствует доступным worker'ам

## GPU worker не стартует

### Симптом

- `worker-gpu` отсутствует или unhealthy
- `docker compose --profile gpu up -d` завершается ошибкой

### Вероятная причина

- на хосте не готова GPU container support
- отсутствует или неполон GPU runtime на хосте

### Как проверить

```bash
docker compose --profile gpu up -d
docker compose ps
docker compose logs --tail=200 worker-gpu
```

### Как исправить

- отдельно от приложения проверьте готовность host GPU container support
- оставьте deployment в CPU mode, пока host GPU runtime не будет исправлен

## Срабатывает fallback to CPU

### Симптом

- ожидалось GPU execution, но логи показывают CPU routing

### Вероятная причина

- задан `GPU_ENABLED=true`, но активного GPU worker нет

### Как проверить

```bash
docker compose logs --tail=200 app worker-chat worker-gpu scheduler
```

Ищите:

- `GPU routing requested ... falling back to cpu`
- `Routing job ... to cpu`

### Как исправить

- запустите рабочий `worker-gpu`
- либо осознанно оставьте CPU mode, если GPU support ещё не готова

## Ответы `403`

### Симптом

- аутентифицированные действия завершаются `403`

### Вероятная причина

- CSRF mismatch
- истёкшая или невалидная session
- revoked token

### Как проверить

- убедитесь, что в браузере ещё есть session cookies
- убедитесь, что для modifying endpoints отправляется CSRF header
- проверьте `app` logs

### Как исправить

- обновите session
- перелогиньтесь
- убедитесь, что клиент корректно отправляет CSRF token

## Ответы `400`

### Симптом

- запрос отклоняется как некорректный

### Вероятная причина

- неверная форма запроса
- неподдерживаемый upload type
- invalid content-type для данного расширения
- слишком много файлов или слишком большой размер

### Как проверить

```bash
docker compose logs --tail=200 app | grep upload_rejected
```

### Как исправить

- исправьте request payload
- используйте поддерживаемый тип файла и допустимый размер

## Ответы `500`

### Симптом

- backend возвращает `500`

### Вероятная причина

- необработанная внутренняя ошибка
- runtime drift
- model runtime failure

### Как проверить

```bash
docker compose logs --tail=200 app worker-chat scheduler
```

### Как исправить

- определите падающий сервис по логам
- при необходимости пересоберите затронутый сервис
- после восстановления прогоните минимальный smoke test

## Связанные документы

- [Администрирование и эксплуатация](ADMIN_ru.md)
- [Install Guide](INSTALL_ru.md)
- [Архитектура](ARCHITECTURE_ru.md)
- [Базовый security baseline](SECURITY_ru.md)

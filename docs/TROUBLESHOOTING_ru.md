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

## Install path ломается на Docker, PyPI или Ollama reachability checks

### Симптом

- `install.sh` останавливается на outbound connectivity checks
- в ошибках фигурируют Docker download, Docker registry, PyPI или Ollama reachability
- package download, Docker pull или model bootstrap падают ещё до healthy состояния приложения

### Вероятная причина

- проблема с host internet connectivity
- проблема с host DNS
- временная недоступность upstream registry/package host
- проблема Docker/container DNS, если host checks проходят, а Docker pull или дальнейшие container lookup всё равно ломаются

### Как проверить

```bash
curl -I --max-time 10 https://registry-1.docker.io/v2/
curl -I --max-time 10 https://pypi.org/simple/
curl -I --max-time 10 https://files.pythonhosted.org/
getent hosts registry-1.docker.io
getent hosts pypi.org
getent hosts files.pythonhosted.org
```

Если ломается именно bootstrap моделей через Ollama, дополнительно проверьте:

```bash
docker compose exec -T ollama ollama list
docker compose logs --tail=100 ollama
```

### Как исправить

- если не работает host DNS или HTTPS reachability, сначала исправьте это и повторяйте installer только после того, как хост стабильно резолвит и достигает нужные endpoints
- если host checks проходят, а Docker pull всё равно падает, переходите к проверке Docker/container DNS ниже
- если временно недоступен upstream registry или package host, подождите и повторите позже
- до восстановления базовой outbound connectivity это проблема инфраструктуры, а не приложения

## Host DNS, `/etc/resolv.conf` или `systemd-resolved` настроены неправильно

### Симптом

- на хосте не резолвятся Docker/PyPI endpoints
- `/etc/resolv.conf` указывает на stub или resolver path, которые на этой VM реально не работают
- DNS-поведение неожиданно меняется после reboot или не совпадает с тем resolver policy, который вы ожидали

### Вероятная причина

- сломанная host DNS configuration
- `/etc/resolv.conf` указывает не на тот resolver file или на stale stub listener
- `systemd-resolved` запущен, но его upstream DNS settings не соответствуют ожидаемой resolver policy хоста

### Как проверить

```bash
cat /etc/resolv.conf
resolvectl status || systemd-resolve --status || true
getent hosts registry-1.docker.io
getent hosts pypi.org
getent hosts files.pythonhosted.org
```

### Как исправить

- приведите host DNS configuration в соответствие с реальной resolver policy вашего окружения до повторного запуска install path
- если используется `systemd-resolved`, убедитесь, что `/etc/resolv.conf` указывает на тот resolver file, который предусмотрен политикой хоста, и что upstream resolvers реально живы
- если `systemd-resolved` не должен использоваться на этом хосте, уберите mismatch, а не оставляйте сломанный stub resolver
- повторяйте install только после того, как повторные host lookup дают стабильный результат
- это работа на уровне host infrastructure, а не application bug

## Host DNS работает, но Docker или контейнеры всё равно не резолвят

### Симптом

- host `curl`/`getent` работают, но Docker pull всё равно падает
- внутри контейнеров ломаются LDAP или внешние lookup, хотя host DNS выглядит healthy
- нестабильность container DNS проявляется во время install path или позже в auth/runtime checks

### Вероятная причина

- Docker daemon унаследовал stale или некорректные DNS settings
- путь container DNS отличается от host DNS
- поведение `systemd-resolved` и DNS inheritance в Docker не согласованы

### Как проверить

```bash
cat /etc/docker/daemon.json 2>/dev/null || true
docker info
docker compose exec -T app bash -lc 'getent hosts <ldap-hostname>'
docker compose exec -T app bash -lc 'getent hosts pypi.org || true'
```

### Как исправить

- если в вашем окружении DNS для Docker daemon управляется явно, исправьте его и перезапустите Docker по правилам вашего хоста
- выровняйте host DNS и Docker/container DNS до повторного запуска installer или рестарта stack
- если проблема затрагивает только AD lookup из контейнеров, installer-managed AD IP override может быть допустимым workaround, но он не чинит общие internet/registry reachability problems
- повторяйте install или model bootstrap только после того, как host и container lookup становятся стабильными

## `ollama pull` ломается из-за сети или DNS

### Симптом

- `ollama pull` падает, зависает или не завершается
- после install path `ollama list` остаётся пустым
- `/health/ready` остаётся degraded, потому что модель так и не была подтянута

### Вероятная причина

- проблема reachability до upstream Ollama path
- проблема host или container DNS
- проблема Docker/container egress

### Как проверить

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
docker compose logs --tail=100 ollama
```

### Как исправить

- сначала устраните host/Docker DNS или outbound network issues
- повторяйте `ollama pull` только после того, как базовые Docker/PyPI/host reachability checks проходят
- если внешний Ollama endpoint недоступен при исправном локальном DNS и egress, подождите и повторите позже
- пока model source недоступен, это проблема вне scope приложения

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

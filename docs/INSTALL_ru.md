# Руководство по установке

## Область действия

Этот документ описывает текущий поддерживаемый сценарий установки Corporate AI Assistant. Он основан на реальном состоянии репозитория:

- развёртывание на Linux VM
- Docker Compose stack
- интеграция с Active Directory / Kerberos / LDAP
- Ollama как локальный inference runtime

Предпочтительный путь установки — `./install.sh`. Для v1.1 это primary/supported deployment path и reference baseline для текущего release family. Exact current HEAD всё ещё нужно отдельно перепроверять через fresh install перед pilot freeze. Ручное развёртывание возможно, но это вторичный сценарий и он требует большей аккуратности со стороны оператора.

Legacy deployment paths, которые могут встречаться в репозитории:

- `install.bat`, `start.bat`, `clean.bat` — legacy Windows helper path, не основной и не validated release baseline
- `deploy/setup-systemd.sh` и `deploy/ai-assistant.service` — legacy systemd Python path, не основной и не validated release baseline

## Поддерживаемый профиль хоста

### Операционная система

- Ubuntu 20.04 или новее
- Debian 11 или новее

Canonical support policy, validation status и границы unsupported platforms зафиксированы в [SUPPORTED_OS.md](SUPPORTED_OS.md).

### Минимальные ресурсы

- 4 vCPU
- 8 GB RAM
- 40 GB свободного места на диске

### Рекомендуемые ресурсы

- 8 vCPU
- 16 GB RAM
- SSD-backed storage

### Опционально

- NVIDIA GPU с рабочими host drivers и Docker GPU runtime для optional профиля `worker-gpu`

## Программные prerequisites

Установщик рассчитан на автоматическую подготовку этих зависимостей на хосте:

- Docker Engine
- Docker Compose plugin
- Kerberos user packages
- LDAP command-line tooling
- Ollama CLI
- OpenSSL и базовые Linux-пакеты, которые нужны для deployment workflow

Installer не ставит и не чинит NVIDIA drivers или NVIDIA container runtime. Подготовка GPU-хоста вне репозитория остаётся задачей оператора.

Если вы разворачиваете систему вручную, эти зависимости нужно подготовить самостоятельно.

## Директории и runtime-компоненты

Compose stack реально включает:

- `nginx`
- `app`
- `sso-proxy`
- `scheduler`
- `worker-chat`
- `worker-siem`
- `worker-batch`
- `worker-parser`
- `postgres`
- `redis`
- `ollama`

`app` и `worker-parser` используют общий parser staging storage, чтобы parser root jobs и parser worker видели один и тот же shared staging contract. `install.sh` сам инициализирует права доступа к этому shared staging во время fresh deploy, поэтому ручной `chmod` после установки не нужен.

Опционально:

- `worker-gpu` через профиль `gpu`

## Prerequisites по AD, DNS и Kerberos

Перед запуском подготовьте:

- DNS-домен AD, например `example.local`
- hostname LDAP-сервера
- hostname Kerberos KDC, если он отличается от LDAP
- Kerberos realm
- base DN, например `dc=example,dc=local`
- сетевую доступность AD и KDC с VM и из контейнеров
- если планируется включать SSO:
  - реальный HTTPS FQDN, который пользователи будут открывать в браузере
  - соответствующий `HTTP/<fqdn>@REALM` SPN
  - HTTP service keytab для этого SPN
  - trusted TLS certificate для реального FQDN
  - domain-joined browsers, настроенные на Negotiate/Kerberos для этого FQDN

Важное примечание по текущей реализации:

- runtime опирается на hostname, а не на raw IP, для совместимости Kerberos/LDAP
- репозиторий также поддерживает installer-managed AD host IP override, если container DNS работает нестабильно

Если во время `install.sh` указан AD IP override, установщик может сгенерировать installer-managed `docker-compose.override.yml`.

## Конфигурация окружения

В репозитории есть шаблон [`.env.example`](../.env.example). Для реального развёртывания используется `.env`.

Ключевые группы параметров:

- AD / LDAP:
  - `LDAP_SERVER`
  - `LDAP_DOMAIN`
  - `LDAP_BASE_DN`
  - `LDAP_NETBIOS_DOMAIN`
  - `AD_SERVER_IP_OVERRIDE`
- Kerberos:
  - `KERBEROS_REALM`
  - `KERBEROS_KDC`
- security:
  - `SECRET_KEY`
  - `REDIS_PASSWORD`
  - cookie settings
  - `TRUSTED_AUTH_PROXY_ENABLED`
  - `SSO_ENABLED`
  - `FORWARDED_ALLOW_IPS`
  - `TRUSTED_PROXY_SOURCE_CIDRS`
  - `SSO_LOGIN_PATH`
  - `SSO_SERVICE_PRINCIPAL`
  - `SSO_KEYTAB_PATH`
  - `ADMIN_DASHBOARD_USERS`
- persistence / PostgreSQL:
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `PERSISTENT_DB_ENABLED`
  - `PERSISTENT_DB_URL`
  - `PERSISTENT_DB_BOOTSTRAP_SCHEMA`
  - `PERSISTENT_DB_SHADOW_COMPARE`
  - `PERSISTENT_DB_READ_THREADS`
  - `PERSISTENT_DB_READ_MESSAGES`
  - `PERSISTENT_DB_DUAL_WRITE_CONVERSATION`
- runtime:
  - `DEFAULT_MODEL`
  - `MODEL_ACCESS_CODING_GROUPS`
  - `MODEL_ACCESS_ADMIN_GROUPS`
  - `INSTALL_TEST_USER`
  - `AUTO_START_OLLAMA`
  - `GPU_ENABLED`
  - `APP_HOST`
  - `APP_PORT`
  - `LOG_LEVEL`

`install.sh` пишет `.env` сам. Для fresh install он сразу включает новый parser file path через `ENABLE_PARSER_STAGE=true` и `ENABLE_PARSER_PUBLIC_CUTOVER=true`, а также текущий PostgreSQL-backed conversation persistence baseline через `PERSISTENT_DB_ENABLED=true`, schema bootstrap, dual-write и read-cutover flags. Если `.env` уже существует и в нём эти значения заданы явно, installer их сохраняет.

Для trusted reverse-proxy SSO оператор должен отдельно проверить `TRUSTED_PROXY_SOURCE_CIDRS`: это должен быть список source addresses/CIDR того reverse proxy, который реально обращается к `app`. Значение loopback подходит только там, где hop до `app` действительно приходит с loopback.

Для Uvicorn proxy-header trust действует отдельный runtime knob `FORWARDED_ALLOW_IPS`. Если он пустой, container startup автоматически ограничивает доверие loopback-адресами и локальными CIDR сетевых интерфейсов самого `app` container, чтобы текущий Docker Compose + nginx baseline продолжал работать без wildcard trust. Для production оператор должен явно задать точный source IP/CIDR reverse proxy hop, который доходит до `app`.

Read-only dashboard operator gate теперь задаётся через `ADMIN_DASHBOARD_USERS`. Это CSV-список usernames; значения trim'ятся и нормализуются той же логикой, что и login usernames. Пустое значение означает, что dashboard закрыт для всех. Runtime больше не использует fallback на тестового пользователя.

Тот же file-processing baseline также поддерживает дополнительные env/settings knobs для parser/file-chat limits: max file count, per-file size, total request size, document-character budget, PDF page cap, image dimension cap и OCR timeout. Шаблон `.env.example` сознательно не перечисляет каждый advanced parser limit по отдельности.

Пример model-access mapping для пилотного AD-стенда может выглядеть так:

```dotenv
MODEL_ACCESS_CODING_GROUPS=AI_Users
MODEL_ACCESS_ADMIN_GROUPS=AI_Admins
```

Это только пример. Runtime не зашивает эти названия групп в код.

## Предпочтительный путь установки: `install.sh`

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
chmod +x install.sh
./install.sh
```

После публикации замените `<repo-url>` на фактический URL репозитория.

При необходимости режим можно задать явно:

```bash
INSTALL_MODE=cpu ./install.sh
INSTALL_MODE=gpu ./install.sh
```

### Что реально делает установщик

`install.sh` сейчас:

1. проверяет OS и модель привилегий
2. запускает system audit и печатает summary по:
   - OS, hostname и IP-адресам
   - CPU, числу ядер, RAM и свободному диску
   - наличию Docker / Compose
   - outbound connectivity checks до Docker download, Docker registry, Ollama и PyPI
   - GPU signals: `nvidia-smi`, `lspci`, видимость Docker GPU runtime и наличие `gpu` profile в Compose
3. рекомендует режим `cpu` или `gpu` и в interactive mode просит подтверждение
4. предупреждает о низких ресурсах и unknown checks
5. для первого deploy требует рабочую outbound connectivity, если хосту ещё нужно скачать Docker packages, Docker images, Ollama installer или модели
6. если система уже была развёрнута и локальные артефакты сохранились, может перейти в post-deploy local repair mode:
   - продолжает local regenerate/reconfigure steps
   - не падает только из-за outbound checks
   - пропускает `docker compose build`, если нужные images уже есть локально
   - честно останавливается позже, если без сети отсутствуют обязательные локальные пакеты или Docker images
7. ставит Docker Engine и Compose plugin, если их нет
8. ставит Kerberos/LDAP-related host packages
9. ставит Ollama CLI, если он отсутствует
10. повторно проверяет GPU prerequisites после появления Docker:
   - если выбран GPU mode и prerequisites готовы, режим сохраняется
   - если используется `INSTALL_MODE=auto`, при неполной GPU readiness installer откатывается на CPU
   - если явно запрошен `INSTALL_MODE=gpu`, а prerequisites всё ещё неполные, installer останавливается и не продолжает “вслепую”
11. запрашивает:
   - AD domain
   - LDAP host
   - optional отдельный Kerberos KDC host
   - base DN
   - optional AD test user для smoke validation
   - optional AD IP override
   - optional comma-separated AD groups для доступа к категории `coding`
   - optional comma-separated AD groups для доступа к категории `admin`
   - нужно ли включать trusted reverse-proxy AD SSO
   - если SSO включается:
     - HTTP service principal, например `HTTP/assistant.example.local@EXAMPLE.LOCAL`
     - путь к keytab внутри контейнера, который должен оставаться под `/etc/corporate-ai-sso/`
   - Redis password
   - JWT secret
12. проверяет, что LDAP/KDC hostnames разрешаются на хосте, если не задан явный AD IP override
13. если SSO включён, проверяет наличие требуемого HTTP service keytab в `deploy/sso/`
14. пишет `.env`, включая `GPU_ENABLED=true|false`, `ENABLE_PARSER_STAGE=true`, `ENABLE_PARSER_PUBLIC_CUTOVER=true`, PostgreSQL/persistence flags, exact-match group mappings для модельных категорий и SSO-related flags
15. генерирует `deploy/krb5.conf`
16. при необходимости пишет installer-managed `docker-compose.override.yml`
17. подготавливает host-side директорию для Ollama models
18. генерирует self-signed TLS material в `deploy/certs/`, если её ещё нет
19. запускает stack в выбранном режиме:
   - CPU mode: обычный `docker compose ...`
   - GPU mode: `docker compose --profile gpu ...`
20. выполняет bootstrap моделей через [`bootstrap_ollama_models.sh`](../bootstrap_ollama_models.sh)
21. ждёт `https://127.0.0.1/health/ready`
22. при наличии test account может выполнить auth smoke check

### Контракт по интернет-доступу

- первый deploy остаётся online-first: если Docker/Compose, Docker images, Ollama installer или model pull ещё нужны, installer честно потребует outbound connectivity
- fully offline fresh install с нуля этот installer не обещает
- повторный запуск installer на уже развёрнутой системе может продолжиться без внешней сети, если:
  - уже есть `.env`
  - уже есть installer state/host manifest или существующие контейнеры стека
  - Docker/Compose уже установлены
  - нужные Docker images уже есть локально
- если этих локальных артефактов нет, installer не маскирует проблему и завершится с явным сообщением на том шаге, где без сети продолжать нельзя

### Что installer не автоматизирует

- установку NVIDIA drivers
- настройку NVIDIA container runtime
- выпуск trusted TLS certificates
- auto-discovery AD topology
- определение правильных AD-групп для категорий model access
- генерацию SPN или service keytab
- настройку browser intranet/trusted-zone для Kerberos SSO
- исправление не-installer-managed `docker-compose.override.yml`

Если GPU обнаружен, но GPU runtime неполный, installer не пытается автоматически “чинить” хост. Он либо откатится на CPU mode, либо остановится — в зависимости от того, как был запрошен режим установки.

## Ручная установка

Используйте manual path только если автоматический installer не подходит вашему окружению.

### 1. Клонировать репозиторий

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
```

### 2. Установить host prerequisites

Минимально текущая документация и установщик предполагают такие пакеты на хосте:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git gnupg jq lsb-release openssl \
  python3 python3-venv python3-pip krb5-user libsasl2-modules-gssapi-mit ldap-utils
```

Затем отдельно установите:

- Docker Engine
- Docker Compose plugin
- Ollama CLI

### 3. Создать environment file

```bash
cp .env.example .env
chmod 600 .env
```

Заполните `.env` реальными значениями для AD, Redis, JWT и runtime.

Для CPU deployment оставьте:

```dotenv
GPU_ENABLED=false
```

Для GPU deployment установите:

```dotenv
GPU_ENABLED=true
```

только если на хосте уже работает GPU container support и вы действительно собираетесь запускать профиль `gpu`.

Если нужен SSO, дополнительно задайте:

```dotenv
TRUSTED_AUTH_PROXY_ENABLED=true
SSO_ENABLED=true
SSO_LOGIN_PATH=/auth/sso/login
SSO_SERVICE_PRINCIPAL=HTTP/assistant.example.local@EXAMPLE.LOCAL
SSO_KEYTAB_PATH=/etc/corporate-ai-sso/http.keytab
MODEL_ACCESS_CODING_GROUPS=AI_Users
MODEL_ACCESS_ADMIN_GROUPS=AI_Admins
```

Эти group names приведены только как пример для пилотного контура. Замените их на реальные AD-группы вашей организации.

### 4. Подготовить Kerberos configuration

Runtime ожидает файл `deploy/krb5.conf`.

Создайте или обновите его под свой домен:

```ini
[libdefaults]
    default_realm = EXAMPLE.LOCAL
    dns_lookup_kdc = false
    dns_lookup_realm = false
    rdns = false

[realms]
    EXAMPLE.LOCAL = {
        kdc = dc01.example.local
        admin_server = dc01.example.local
    }

[domain_realm]
    .example.local = EXAMPLE.LOCAL
    example.local = EXAMPLE.LOCAL
```

### 5. Подготовить SSO keytab material, если SSO включён

Создайте директорию и положите туда HTTP service keytab:

```bash
mkdir -p deploy/sso
chmod 700 deploy/sso
install -m 600 /path/to/http.keytab deploy/sso/http.keytab
```

Имя файла keytab должно совпадать с basename из `SSO_KEYTAB_PATH`. При значении по умолчанию ожидается файл `deploy/sso/http.keytab`.

### 6. Подготовить TLS certificates

Приложение рассчитано на работу за Nginx. В текущем репозитории используются:

- `deploy/certs/server.crt`
- `deploy/certs/server.key`

Для локального или pilot-использования можно создать self-signed сертификаты:

```bash
mkdir -p deploy/certs
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout deploy/certs/server.key \
  -out deploy/certs/server.crt
```

### 7. Запустить stack

CPU mode:

```bash
docker compose build
docker compose up -d
```

GPU mode:

```bash
docker compose build
docker compose --profile gpu up -d
```

Используйте GPU mode только если:

- в `.env` установлено `GPU_ENABLED=true`
- на хосте работают NVIDIA drivers
- у Docker есть рабочий GPU runtime access

## Bootstrap моделей

Приложению нужна хотя бы одна доступная модель Ollama.

Installer уже пытается выполнить bootstrap. При ручной установке можно запустить:

```bash
./bootstrap_ollama_models.sh
```

Полезные проверки:

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
docker compose exec -T ollama ollama pull gemma2:2b
```

Если моделей нет, stack может подняться, но chat-запросы будут падать с model-unavailable condition.

## Запуск, остановка и рестарт

Запуск:

```bash
docker compose up -d
```

Пересборка и рестарт:

```bash
docker compose up -d --build
```

Остановка:

```bash
docker compose down
```

## Uninstall

Используйте repository uninstall flow, когда нужно снять текущее развёртывание без длинного ручного cleanup checklist.

Safe mode:

```bash
bash uninstall.sh --dry-run
bash uninstall.sh --yes
```

Factory-reset mode:

```bash
sudo bash uninstall.sh --dry-run --factory-reset
sudo bash uninstall.sh --yes --factory-reset
```

Factory-reset с удалением repo и deferred self-delete:

```bash
sudo bash uninstall.sh --dry-run --factory-reset --remove-repo
sudo bash uninstall.sh --yes --factory-reset --remove-repo
```

Поведение safe mode:

- удаляет текущий Docker Compose stack этого репозитория, включая named Compose volumes
- удаляет project-local generated state: `.env`, `deploy/krb5.conf`, installer-managed `docker-compose.override.yml`, текущую Ollama host directory и `.install`
- сохраняет host-installed Docker/Ollama packages, apt repositories, membership в группе `docker` и unrelated Docker assets на хосте
- сохраняет `deploy/sso` keytab material, потому что это operator-provided secret, а не артефакт, который генерирует installer

Поведение factory-reset:

- сохраняет всю safe-mode cleanup semantics
- удаляет installer-owned host dependencies только там, где expanded install manifest доказывает ownership
- может удалить exact apt packages, записанные как installer-installed
- может восстановить или удалить Docker repo/keyring только когда ownership installer доказан
- может восстановить или удалить Docker/Ollama host service state только если manifest доказывает, что installer его изменял
- может убрать membership в группе `docker` только когда manifest доказывает, что installer её добавил
- использует durable host manifest в `/var/lib/corporate-ai-assistant/host-state.env`, поэтому rollback installer-owned host dependencies переживает safe uninstall плюс reinstall cycle
- по-прежнему не трогает unrelated Docker assets и unrelated host configuration

Удаление repo и self-delete:

- `--remove-repo` требует `--factory-reset`
- удаление repo выполняется через deferred background cleanup после завершения основного скрипта, поэтому текущий script может безопасно удалить собственный репозиторий
- deferred helper удаляет текущий uninstall log и собственный helper file, поэтому успешный `--remove-repo` run не должен оставлять новые `/tmp/corporate-ai-uninstall-*` helper или log traces
- `--remove-repo` намеренно сделан явным, потому что он удаляет всю директорию репозитория

Manifest и TLS handling:

- если install manifest подтверждает, что self-signed TLS material был сгенерирован через `install.sh`, `uninstall.sh` удаляет `deploy/certs`
- если ownership installer не доказан, `deploy/certs` сохраняется, чтобы не удалить operator-managed certificate material
- установки, созданные до durable host manifest flow, могут выполнять только частичный factory-reset rollback, потому что cumulative ownership installer-owned host dependencies тогда ещё не записывался

## Проверка health

### Состояние контейнеров

```bash
docker compose ps
```

### Liveness и readiness

```bash
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

`/health/ready` считается healthy только когда приложение видит:

- Redis
- свежий heartbeat scheduler
- хотя бы один working chat worker
- schedulable capacity для chat workloads

### Начальные логи

```bash
docker compose logs --tail=100 app scheduler worker-chat nginx
```

## Первый вход

Откройте:

```text
https://<vm-ip>
```

Важно:

- браузер может предупредить о self-signed certificate
- нужен валидный AD account
- успешный логин переводит пользователя на `/chat`

## Базовый troubleshooting установки

Если install path ломается из-за reachability до Docker/PyPI/Ollama, host DNS, `/etc/resolv.conf`, `systemd-resolved` или drift между host/container DNS, используйте выделенный network troubleshooting section в [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md).

### `health/ready` не становится healthy

Проверьте:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat ollama nginx
docker compose exec -T ollama ollama list
```

### Ошибки Kerberos или LDAP

Проверьте:

- что LDAP/KDC заданы hostname, а не raw IP
- `deploy/krb5.conf`
- DNS resolution на хосте и в контейнерах
- optional AD IP override, если container DNS нестабилен

### Модель отсутствует

Проверьте:

```bash
docker compose exec -T ollama ollama list
./bootstrap_ollama_models.sh
```

### GPU profile не стартует

Обычно это означает, что на хосте не готова GPU container support. CPU deployment path остаётся базовым поддерживаемым режимом.

## Связанные документы

- [README.md](../README.md)
- [Architecture](ARCHITECTURE_ru.md)
- [Администрирование и эксплуатация](ADMIN_ru.md)
- [Troubleshooting](TROUBLESHOOTING_ru.md)
- [Базовый security baseline](SECURITY_ru.md)

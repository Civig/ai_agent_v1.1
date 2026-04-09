# Границы пилота

## Назначение

Этот документ жёстко фиксирует, что входит и что не входит в текущий pilot scope для baseline `3396058`.

## Матрица границ пилота

| Область | Статус в пилоте | Что это означает |
| --- | --- | --- |
| Supported install path | Входит | Только Linux VM + Docker Compose + `install.sh` как primary/supported path |
| Supported host family | Входит | Ubuntu `20.04+` и Debian `11+` как supported installer targets; safest recorded validation point в release family: Ubuntu 24.04 |
| Password login | Входит | Kerberos + LDAP-backed password flow является supported pilot auth mode |
| Trusted reverse-proxy SSO | Не входит в baseline scope | Может рассматриваться только как отдельный validation track при наличии real infra proof |
| Normal chat | Входит | Обычный web chat входит в pilot acceptance baseline |
| File-chat | Входит | Входит для поддерживаемых типов файлов и текущих parser/file limits |
| Operator dashboard | Входит | Read-only `/admin/dashboard` входит как operator-only monitoring surface |
| GPU mode | Не входит в baseline acceptance | Допустим только как отдельный GPU validation track по playbook |
| Persistence baseline | Входит с оговоркой | Реализованный Redis/PostgreSQL transitional baseline присутствует, но не продаётся как fully finalized storage platform |
| Safe uninstall | Входит | `bash uninstall.sh --yes` входит в supported operator toolkit |
| Factory-reset uninstall | Входит с оговоркой | `--factory-reset` поддерживается только в пределах manifest-proven installer ownership |

## Базовые предпосылки пилота

Текущий pilot scope предполагает:

- внутренний Linux VM deployment
- Docker Compose deployment, а не Kubernetes и не legacy systemd path
- доступность AD / Kerberos / LDAP с хоста и из контейнеров
- локальный inference через Ollama
- internal-only operator access к dashboard
- CPU-first baseline как основную точку пилота

## Поддерживаемые возможности оператора

В pilot scope входят такие operator capabilities:

- выполнить clean install по `install.sh`
- проверить `health/live` и `health/ready`
- войти под валидным AD account по password flow
- выполнить normal chat и file-chat smoke checks
- открыть `/admin/dashboard` и проверить summary/live/history/events
- посмотреть основные runtime logs и queue/worker состояние
- выполнить safe uninstall и при необходимости manifest-scoped factory-reset

## Что сознательно вне границ пилота

В текущий pilot scope сознательно не входят:

- обещание enterprise SSO readiness без отдельной validation на реальном FQDN/SPN/keytab path
- обещание GPU readiness без отдельной validation на dedicated GPU host
- HA Redis, HA control plane или distributed rollout
- external secret manager
- centralized SIEM forwarding или полноценный centralized observability stack
- production-ready dashboard RBAC / claim model
- DLP, antivirus, sandbox-based file scanning
- finalized durable user/quota/audit platform
- unsupported OS families и non-Linux deployment targets

## Правило против расползания границ

Если capability не проходит как:

- already implemented in baseline
- documented in current source of truth
- accepted by pilot limitations
- separately validated where required

то она не должна считаться частью текущего пилота.

## Связанные документы

- [PILOT_BASELINE_ru.md](PILOT_BASELINE_ru.md)
- [PILOT_LIMITATIONS_ru.md](PILOT_LIMITATIONS_ru.md)
- [PILOT_ACCEPTANCE_CHECKLIST_ru.md](PILOT_ACCEPTANCE_CHECKLIST_ru.md)

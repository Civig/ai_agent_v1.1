# Pilot Scope

## Purpose

This document fixes exactly what is in and out of scope for the current pilot on baseline `3396058`.

## Pilot scope matrix

| Area | Pilot status | What this means |
| --- | --- | --- |
| Supported install path | In scope | Linux VM + Docker Compose + `install.sh` only as the primary/supported path |
| Supported host family | In scope | Ubuntu `20.04+` and Debian `11+` as supported installer targets; the safest recorded validation point in the release family is Ubuntu 24.04 |
| Password login | In scope | The Kerberos + LDAP-backed password flow is the supported pilot auth mode |
| Trusted reverse-proxy SSO | Not in baseline scope | It may be considered only as a separate validation track with real infrastructure proof |
| Normal chat | In scope | Standard web chat is part of the pilot acceptance baseline |
| File-chat | In scope | Included for the supported file types and current parser/file limits |
| Operator dashboard | In scope | The read-only `/admin/dashboard` is included as an operator-only monitoring surface |
| GPU mode | Not in baseline acceptance | It is allowed only as a separate GPU validation track using the playbook |
| Persistence baseline | In scope with a boundary | The implemented Redis/PostgreSQL transitional baseline is present, but it must not be sold as a fully finalized storage platform |
| Safe uninstall | In scope | `bash uninstall.sh --yes` is part of the supported operator toolkit |
| Factory-reset uninstall | In scope with a boundary | `--factory-reset` is supported only within manifest-proven installer ownership |

## Supported pilot assumptions

The current pilot scope assumes:

- internal Linux VM deployment
- Docker Compose deployment, not Kubernetes and not the legacy systemd path
- AD / Kerberos / LDAP reachable from the host and from containers
- local inference through Ollama
- internal-only operator access to the dashboard
- a CPU-first baseline as the main pilot path

## Supported operator capabilities

The following operator capabilities are in scope for the pilot:

- perform a clean install through `install.sh`
- verify `health/live` and `health/ready`
- log in with a valid AD account through the password flow
- run normal chat and file-chat smoke checks
- open `/admin/dashboard` and verify `summary/live/history/events`
- inspect the main runtime logs and queue/worker state
- run safe uninstall and, when needed, manifest-scoped factory-reset

## What is intentionally out of scope

The following items are intentionally out of scope for the current pilot:

- any promise of enterprise SSO readiness without separate validation on the real FQDN/SPN/keytab path
- any promise of GPU readiness without separate validation on a dedicated GPU host
- HA Redis, HA control plane, or distributed rollout
- an external secret manager
- centralized SIEM forwarding or a full centralized observability stack
- a production-ready dashboard RBAC / claim model
- DLP, antivirus, or sandbox-based file scanning
- a finalized durable user/quota/audit platform
- unsupported OS families and non-Linux deployment targets

## Anti-scope-creep rule

If a capability is not:

- already implemented in the baseline
- documented in the current source of truth
- accepted by the pilot limitations
- separately validated where required

then it must not be treated as part of the current pilot.

## Related documents

- [PILOT_BASELINE_en.md](PILOT_BASELINE_en.md)
- [PILOT_LIMITATIONS_en.md](PILOT_LIMITATIONS_en.md)
- [PILOT_ACCEPTANCE_CHECKLIST_en.md](PILOT_ACCEPTANCE_CHECKLIST_en.md)

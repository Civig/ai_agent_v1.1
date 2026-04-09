# ai_agent_v1.1 — Corporate AI Assistant

[Primary Russian document](README.ru.md) | [Documentation map](docs/INDEX.md)

Corporate AI Assistant `ai_agent_v1.1` is an internal/on-prem AI assistant for Linux VM deployment in Active Directory environments.

This repository contains the `v1.1.0` release baseline plus later hardening and documentation updates already present in the current branch. The supported deployment baseline remains Linux VM + Docker Compose + `install.sh`. Legacy helper files may remain in the repository for reference, but they are not the primary supported path.

## Current State Summary

- FastAPI backend with web chat
- Kerberos + LDAP-backed password login
- optional trusted reverse-proxy SSO path
- Redis-backed scheduler, workers, rate limiting, and session state
- PostgreSQL-backed conversation persistence groundwork with dual-write/read-cutover flags
- Ollama as the local inference runtime
- parser-based file-chat path with dedicated `worker-parser` and shared staging
- read-only operator dashboard with live telemetry, history, and events
- Russian-first operator docs with synced English documents

## Reading Order

1. [Documentation Map](docs/INDEX.md) — document roles and navigation
2. [Pilot Baseline (EN)](docs/PILOT_BASELINE_en.md) — pilot baseline candidate, evidence boundary, and validation status
3. [QUICKSTART.md](QUICKSTART.md) — shortest first launch path
4. [Supported OS Matrix](docs/SUPPORTED_OS.md) — validated vs supported vs unsupported platform status
5. [Install Guide (EN)](docs/INSTALL_en.md) or [Install Guide (RU)](docs/INSTALL_ru.md) — full installation and installer behavior
6. [Production Deployment Guide](docs/PRODUCTION_DEPLOY.md) — production-only deltas and exposure guidance
7. [Administration (EN)](docs/ADMIN_en.md) / [Administration (RU)](docs/ADMIN_ru.md) — day-2 operations
8. [Security Baseline (EN)](docs/SECURITY_en.md) / [Security Baseline (RU)](docs/SECURITY_ru.md) — product security baseline
9. [Troubleshooting (EN)](docs/TROUBLESHOOTING_en.md) / [Troubleshooting (RU)](docs/TROUBLESHOOTING_ru.md) — full diagnostics and recovery
10. [Architecture (EN)](docs/ARCHITECTURE_en.md) / [Architecture (RU)](docs/ARCHITECTURE_ru.md) — implemented system design

## Supported Deployment Baseline

- Linux VM
- Docker Compose
- Nginx TLS ingress
- Redis
- Ollama
- Kerberos / LDAP-backed authentication
- installer-driven deployment through `install.sh`

## Current Validation Boundaries

- the current branch is a clean code/docs baseline, but the exact current HEAD should still be re-validated through a fresh install before a pilot freeze
- GPU deployment requires separate target-host validation
- trusted reverse-proxy SSO requires separate infrastructure/runtime validation on the final FQDN/SPN/keytab path

## Pilot Baseline Summary

- pilot baseline candidate: `33960581772787b162a0885bc2181f650f22a168` (`3396058`) on `main`
- the baseline already includes supported Linux VM + Docker Compose + `install.sh`, password login, normal chat, file-chat, the read-only operator dashboard, and the uninstall/factory-reset flow
- still not separately proven: fresh install re-validation of the exact current HEAD, GPU host validation, and real-infrastructure SSO validation
- the pilot is meant to prove the CPU-first baseline, operator handoff readiness, and honest limitations, not to promise HA, enterprise SSO, or GPU readiness by default
- pilot package: [docs/PILOT_BASELINE_en.md](docs/PILOT_BASELINE_en.md), [docs/PILOT_SCOPE_en.md](docs/PILOT_SCOPE_en.md), [docs/PILOT_LIMITATIONS_en.md](docs/PILOT_LIMITATIONS_en.md), [docs/PILOT_ACCEPTANCE_CHECKLIST_en.md](docs/PILOT_ACCEPTANCE_CHECKLIST_en.md), [docs/GPU_VALIDATION_PLAYBOOK_en.md](docs/GPU_VALIDATION_PLAYBOOK_en.md), [docs/PILOT_RUNBOOK_en.md](docs/PILOT_RUNBOOK_en.md)

## Documentation

- [Documentation Map](docs/INDEX.md)
- [Pilot Baseline (EN)](docs/PILOT_BASELINE_en.md)
- [Pilot Scope (EN)](docs/PILOT_SCOPE_en.md)
- [Pilot Limitations (EN)](docs/PILOT_LIMITATIONS_en.md)
- [Pilot Acceptance Checklist (EN)](docs/PILOT_ACCEPTANCE_CHECKLIST_en.md)
- [GPU Validation Playbook (EN)](docs/GPU_VALIDATION_PLAYBOOK_en.md)
- [Pilot Runbook (EN)](docs/PILOT_RUNBOOK_en.md)
- [Supported OS Matrix](docs/SUPPORTED_OS.md)
- [QUICKSTART.md](QUICKSTART.md)
- [Install Guide (EN)](docs/INSTALL_en.md)
- [Install Guide (RU)](docs/INSTALL_ru.md)
- [Production Deployment Guide](docs/PRODUCTION_DEPLOY.md)
- [Administration (EN)](docs/ADMIN_en.md)
- [Administration (RU)](docs/ADMIN_ru.md)
- [Security Baseline (EN)](docs/SECURITY_en.md)
- [Security Baseline (RU)](docs/SECURITY_ru.md)
- [Troubleshooting (EN)](docs/TROUBLESHOOTING_en.md)
- [Troubleshooting (RU)](docs/TROUBLESHOOTING_ru.md)
- [Architecture (EN)](docs/ARCHITECTURE_en.md)
- [Architecture (RU)](docs/ARCHITECTURE_ru.md)
- [Changelog](CHANGELOG.md)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

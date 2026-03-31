# ai_agent_v1.1 — Corporate AI Assistant

[Primary Russian document](README.ru.md) | [Documentation map](docs/INDEX.md)

Corporate AI Assistant `ai_agent_v1.1` is an internal/on-prem AI assistant for Linux VM deployment in Active Directory environments.

This repository contains the `v1.1.0` release baseline plus later hardening and documentation updates already present in the current branch. The supported deployment baseline remains Linux VM + Docker Compose + `install.sh`. Legacy helper files may remain in the repository for reference, but they are not the primary supported path.

## Current State Summary

- FastAPI backend with web chat
- Kerberos + LDAP-backed password login
- optional trusted reverse-proxy SSO path
- Redis-backed scheduler, workers, rate limiting, and session state
- Ollama as the local inference runtime
- parser-based file-chat path with dedicated `worker-parser` and shared staging
- Russian-first operator docs with synced English documents

## Reading Order

1. [Documentation Map](docs/INDEX.md) — document roles and navigation
2. [QUICKSTART.md](QUICKSTART.md) — shortest first launch path
3. [Supported OS Matrix](docs/SUPPORTED_OS.md) — validated vs supported vs unsupported platform status
4. [Install Guide (EN)](docs/INSTALL_en.md) or [Install Guide (RU)](docs/INSTALL_ru.md) — full installation and installer behavior
5. [Production Deployment Guide](docs/PRODUCTION_DEPLOY.md) — production-only deltas and exposure guidance
6. [Administration (EN)](docs/ADMIN_en.md) / [Administration (RU)](docs/ADMIN_ru.md) — day-2 operations
7. [Security Baseline (EN)](docs/SECURITY_en.md) / [Security Baseline (RU)](docs/SECURITY_ru.md) — product security baseline
8. [Troubleshooting (EN)](docs/TROUBLESHOOTING_en.md) / [Troubleshooting (RU)](docs/TROUBLESHOOTING_ru.md) — full diagnostics and recovery
9. [Architecture (EN)](docs/ARCHITECTURE_en.md) / [Architecture (RU)](docs/ARCHITECTURE_ru.md) — implemented system design

## Supported Deployment Baseline

- Linux VM
- Docker Compose
- Nginx TLS ingress
- Redis
- Ollama
- Kerberos / LDAP-backed authentication
- installer-driven deployment through `install.sh`

## Documentation

- [Documentation Map](docs/INDEX.md)
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

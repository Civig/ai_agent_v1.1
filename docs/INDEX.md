# Documentation Map

This file defines the current documentation map and document roles for `ai_agent_v1.1`.
Этот файл задает текущую карту документации и роли документов для `ai_agent_v1.1`.

Russian documents are the primary operator reference. English documents are kept as synced companion versions.
Русские документы остаются основными operator docs. Английские документы поддерживаются как синхронизированные companion-версии.

## Start Here / С чего начать

- Primary document / Основной документ: [README.ru.md](../README.ru.md)
- Secondary document / Вторичный документ: [README.md](../README.md)
- When to read / Когда читать: first, before installation, integration, or operations work
- Covers / Что покрывает: product overview, supported deployment baseline, documentation entrypoint, reading order
- Does not cover / Что не покрывает: full installation steps, day-2 operations, deep security baseline, full troubleshooting

## Quick Start / Быстрый старт

- Primary document / Основной документ: [QUICKSTART.md](../QUICKSTART.md)
- When to read / Когда читать: when you need the shortest path to a first launch on a fresh Linux VM
- Covers / Что покрывает: brief prerequisites, `install.sh`, first launch, first verification, where to go next
- Does not cover / Что не покрывает: manual installation, full installer behavior, production hardening, full troubleshooting

## Full Install / Полная установка

- Primary document / Основной документ: [INSTALL_ru.md](INSTALL_ru.md)
- Synced companion / Синхронизированная companion-версия: [INSTALL_en.md](INSTALL_en.md)
- Supported OS matrix / Матрица поддерживаемых ОС: [SUPPORTED_OS.md](SUPPORTED_OS.md)
- When to read / Когда читать: when preparing or performing a supported installation
- Covers / Что покрывает: host profile, prerequisites, environment configuration, installer behavior, manual installation, safe uninstall, factory-reset uninstall, first login, install verification
- Does not cover / Что не покрывает: day-2 operations, full production hardening, architecture internals

## Administration / Администрирование

- Primary document / Основной документ: [ADMIN_ru.md](ADMIN_ru.md)
- Synced companion / Синхронизированная companion-версия: [ADMIN_en.md](ADMIN_en.md)
- When to read / Когда читать: after deployment for operations, maintenance, smoke checks, degradation response, and rollback basics
- Covers / Что покрывает: lifecycle commands, logs, health checks, model operations, queue checks, maintenance routines
- Does not cover / Что не покрывает: full installation walkthrough, architecture design rationale, repository contribution policy

## Architecture / Архитектура

- Primary document / Основной документ: [ARCHITECTURE_ru.md](ARCHITECTURE_ru.md)
- Synced companion / Синхронизированная companion-версия: [ARCHITECTURE_en.md](ARCHITECTURE_en.md)
- When to read / Когда читать: when you need the implemented system design, component boundaries, request paths, and current limitations
- Covers / Что покрывает: current architecture, components, request flows, storage model, implemented vs planned scope
- Does not cover / Что не покрывает: installation runbook, production rollout checklist, operator incident recovery

## Security / Безопасность

- Primary document / Основной документ: [SECURITY_ru.md](SECURITY_ru.md)
- Synced companion / Синхронизированная companion-версия: [SECURITY_en.md](SECURITY_en.md)
- Repository policy entrypoint / Корневой policy entrypoint: [../SECURITY.md](../SECURITY.md)
- When to read / Когда читать: before pilot, production exposure, SSO enablement, or security review
- Covers / Что покрывает: product security baseline, auth/session model, transport security, upload baseline, known gaps, operator-owned controls
- Does not cover / Что не покрывает: vulnerability reporting workflow details outside the repository policy entrypoint

## Production Deployment / Прод-развертывание

- Primary document / Основной документ: [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md)
- Supporting documents / Поддерживающие документы: [INSTALL_ru.md](INSTALL_ru.md), [INSTALL_en.md](INSTALL_en.md), [SECURITY_ru.md](SECURITY_ru.md), [SECURITY_en.md](SECURITY_en.md), [ADMIN_ru.md](ADMIN_ru.md), [ADMIN_en.md](ADMIN_en.md)
- When to read / Когда читать: when moving from a standard install path to a real production rollout
- Covers / Что покрывает: production-specific deltas, TLS/FQDN expectations, exposure boundaries, firewall guidance, hardening references, rollout checklist
- Does not cover / Что не покрывает: full installer walkthrough, full manual installation, routine day-2 operations

## Troubleshooting / Диагностика

- Primary document / Основной документ: [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md)
- Synced companion / Синхронизированная companion-версия: [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md)
- Root triage entrypoint / Корневой triage entrypoint: [../TROUBLESHOOTING.md](../TROUBLESHOOTING.md)
- When to read / Когда читать: when first verification or runtime behavior is unhealthy, degraded, or unexpected
- Covers / Что покрывает: symptom-based diagnostics, probable causes, checks, and fixes
- Does not cover / Что не покрывает: full architecture explanation, full installation instructions, repository contribution workflow

## Supporting And Reference Docs / Вспомогательные и справочные документы

- [SUPPORTED_OS.md](SUPPORTED_OS.md) - canonical supported OS matrix and validation status
- [../PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md) - repository layout reference
- [../CHANGELOG.md](../CHANGELOG.md) - release and change history
- [../CONTRIBUTING.md](../CONTRIBUTING.md) - contribution workflow and coding style
- [../SECURITY.md](../SECURITY.md) - repository-level vulnerability reporting entrypoint

## Recommended Reading Order / Рекомендуемый маршрут чтения

1. [README.ru.md](../README.ru.md) or [README.md](../README.md)
2. [../QUICKSTART.md](../QUICKSTART.md)
3. [INSTALL_ru.md](INSTALL_ru.md) or [INSTALL_en.md](INSTALL_en.md)
4. [PRODUCTION_DEPLOY.md](PRODUCTION_DEPLOY.md) if a production rollout is planned
5. [ADMIN_ru.md](ADMIN_ru.md) / [ADMIN_en.md](ADMIN_en.md)
6. [SECURITY_ru.md](SECURITY_ru.md) / [SECURITY_en.md](SECURITY_en.md)
7. [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md) / [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md)
8. [ARCHITECTURE_ru.md](ARCHITECTURE_ru.md) / [ARCHITECTURE_en.md](ARCHITECTURE_en.md)

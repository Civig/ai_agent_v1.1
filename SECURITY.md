# Security Policy

## Scope

This root file is the repository-level security policy and vulnerability-reporting entrypoint. It is not the full product security baseline.

This repository is intended for internal enterprise deployment. Operators remain responsible for organization-approved TLS, secure Active Directory / Kerberos connectivity, host hardening, and secrets management.

## Reporting a Vulnerability

Please do not publish sensitive security findings as a public issue with exploit details.

If GitHub private vulnerability reporting is enabled for the repository, use that channel. Otherwise, contact the repository owner directly through the contact method listed on GitHub and share:

- a clear description of the issue
- impact and affected components
- reproduction steps
- suggested remediation, if available

## Product Security Documentation

- [docs/SECURITY_ru.md](docs/SECURITY_ru.md) - primary product security baseline
- [docs/SECURITY_en.md](docs/SECURITY_en.md) - synced English companion
- [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md) - production deployment deltas, exposure boundaries, and hardening references
- [docs/INDEX.md](docs/INDEX.md) - documentation map and document roles

Use the product security documents for the implemented auth/session model, transport security, upload and file-security baseline, known gaps, and operator-owned hardening expectations.

# ai_agent_v1.1 — Corporate AI Assistant

[Primary Russian document](README.ru.md) | [English summary](README.md)

This workspace prepares a clean release snapshot of Corporate AI Assistant for internal and pilot deployments in Active Directory environments. The validated code baseline behind this release is `bab04bf`.

For v1.1, the primary and supported deployment path is explicitly: Linux VM + Docker Compose + `install.sh`. Legacy helper files may remain in the repository, but they are not the primary validated release baseline.

The supported deployment model remains:

- Linux VM
- Docker Compose
- Nginx TLS ingress
- Redis
- Ollama
- Kerberos / LDAP-backed authentication
- installer-driven deployment through `install.sh`

## What This Release Snapshot Contains

- FastAPI backend with web chat
- password login backed by Kerberos + LDAP
- optional trusted reverse-proxy SSO path
- Redis-backed scheduler, workers, rate limiting, and session state
- installer-driven deployment through `install.sh`
- Russian-first operator documentation with synced English docs

## Validated Baseline Fixes Included

- deduplicated AD host aliases in installer-managed compose override generation
- explicit `request` passed to login template responses
- LDAP GSSAPI lookup uses `ldapsearch -N`
- explicit `request` passed to chat template responses

## Quick Start

Replace `<repo-url>` with the actual repository URL after publication:

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
chmod +x install.sh
./install.sh
```

Then verify:

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

## Important Notes

- self-signed TLS is still the default installer path for first-run internal validation
- production deployments should replace self-signed TLS material with a trusted certificate chain
- hostname/SPN consistency still matters for Kerberos / LDAP interoperability
- lab values such as `srv-ad`, `srv-ad.corp.local`, or `10.10.10.10` are examples only, not universal release constants

## Documentation

- [README.ru.md](README.ru.md) — primary product overview
- [Install Guide (RU)](docs/INSTALL_ru.md)
- [Install Guide (EN)](docs/INSTALL_en.md)
- [Architecture (RU)](docs/ARCHITECTURE_ru.md)
- [Architecture (EN)](docs/ARCHITECTURE_en.md)
- [Security Baseline (RU)](docs/SECURITY_ru.md)
- [Security Baseline (EN)](docs/SECURITY_en.md)
- [Troubleshooting (RU)](docs/TROUBLESHOOTING_ru.md)
- [Troubleshooting (EN)](docs/TROUBLESHOOTING_en.md)
- [Production Deployment Guide](docs/PRODUCTION_DEPLOY.md)
- [Changelog](CHANGELOG.md)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

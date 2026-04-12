# Quick Start

This guide is the shortest path to a first working Corporate AI Assistant deployment on a fresh Ubuntu or Debian VM.

For the current release-candidate line for `v1.2.0`, this remains the primary and supported first-launch path: Linux VM + Docker Compose + `install.sh`.
`v1.1.0` is the earlier baseline; the final `v1.2.0` tag is created only after the final TEST VM validation pass.
Use this document for the shortest path only. For full prerequisites, installer behavior, manual installation, and production-specific guidance, continue to the install and production documents linked below.

## Brief Prerequisites

- Ubuntu 20.04+ or Debian 11+
- 8 GB RAM minimum
- network access to Active Directory / Kerberos / LDAP
- shell access with the privileges required to run `install.sh`

## 1. Clone The Repository

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
```

Replace `<repo-url>` with the actual repository URL after publication.

## 2. Run The Installer

```bash
chmod +x install.sh
./install.sh
```

`install.sh` prepares the standard supported baseline. For full installer behavior and manual alternatives, use [docs/INSTALL_en.md](docs/INSTALL_en.md) or [docs/INSTALL_ru.md](docs/INSTALL_ru.md).

## 3. Open The Web UI

```text
https://<vm-ip>
```

The browser may warn about the self-signed certificate on first access.

## 4. Verify First Launch

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

On a fresh install, the parser file-chat path is enabled by default. Make sure the Compose stack includes `worker-parser` together with `app`, `scheduler`, and `worker-chat`.

## Next Reading

- [docs/INDEX.md](docs/INDEX.md)
- [docs/INSTALL_en.md](docs/INSTALL_en.md)
- [docs/INSTALL_ru.md](docs/INSTALL_ru.md)
- [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md)
- [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md)

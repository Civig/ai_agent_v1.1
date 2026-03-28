# Quick Start

This guide is the shortest path to a working Corporate AI Assistant deployment on a fresh Ubuntu or Debian VM.

For v1.1, this is the primary and supported deployment path: Linux VM + Docker Compose + `install.sh`. Do not mix this quick-start flow with the legacy Windows `.bat` helpers or the legacy systemd Python service path kept in the repository for reference.

## 1. Clone the repository

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
```

Replace `<repo-url>` with the actual repository URL after publication.

## 2. Run the installer

```bash
chmod +x install.sh
./install.sh
```

The installer will:

- validate the host OS and privileges
- install Docker, Docker Compose, Kerberos / LDAP packages, and the Ollama CLI
- ask for your AD domain, LDAP server, base DN, and deployment secrets
- generate `.env`, `deploy/krb5.conf`, and self-signed TLS certificates
- build and start the Docker Compose stack
- pull the default Ollama model
- wait for `https://127.0.0.1/health/ready`

## 3. Open the web UI

```text
https://<vm-ip>
```

The browser may warn about the self-signed certificate on first access.

## 4. Verify the deployment

```bash
docker compose ps
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

## 5. Manage models

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
```

## Requirements

- Ubuntu 20.04+ or Debian 11+
- 8 GB RAM minimum
- Docker-compatible CPU virtualization
- Network connectivity to Active Directory / Kerberos KDC

## Troubleshooting

### `health/ready` never returns `200`

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat nginx
```

### LDAP / Kerberos fails with `No worthy mechs found`

Check:

- `libsasl2-modules-gssapi-mit` is installed
- `LDAP_SERVER` and `KERBEROS_KDC` use hostnames, not raw IPs
- `deploy/krb5.conf` matches the AD realm

### The model is missing

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
```

## Next Reading

- [README.md](README.md)
- [docs/PRODUCTION_DEPLOY.md](docs/PRODUCTION_DEPLOY.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

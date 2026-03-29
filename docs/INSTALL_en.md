# Installation Guide

## Scope

This guide documents the currently supported installation path for Corporate AI Assistant. It is based on the repository as it exists today:

- Linux VM deployment
- Docker Compose stack
- Active Directory / Kerberos / LDAP integration
- Ollama as the local inference runtime

The preferred path is `./install.sh`. For v1.1, this is the primary/supported deployment path and the only validated release baseline. Manual deployment is possible, but it is a secondary path and requires more operator care.

Legacy deployment paths that may still appear in the repository:

- `install.bat`, `start.bat`, `clean.bat` are a legacy Windows helper path and not the primary validated release baseline
- `deploy/setup-systemd.sh` and `deploy/ai-assistant.service` are a legacy systemd Python path and not the primary validated release baseline

## Supported Host Profile

### Operating system

- Ubuntu 20.04 or newer
- Debian 11 or newer

For the canonical support policy, validation status, and unsupported-platform boundaries, use [SUPPORTED_OS.md](SUPPORTED_OS.md).

### Minimum hardware

- 4 CPU cores
- 8 GB RAM
- 40 GB free disk

### Recommended hardware

- 8 CPU cores
- 16 GB RAM
- SSD-backed storage

### Optional

- NVIDIA GPU with working host drivers and Docker GPU runtime for the optional `worker-gpu` profile

## Software Prerequisites

The installer is designed to prepare these dependencies automatically on the host:

- Docker Engine
- Docker Compose plugin
- Kerberos user packages
- LDAP command-line tooling
- Ollama CLI
- OpenSSL and base Linux packages needed by the deployment workflow

The installer does not install or repair NVIDIA drivers or the NVIDIA container runtime. GPU host preparation outside the repository is still the operator's responsibility.

If you install manually, you must provide these dependencies yourself.

## Directory and Runtime Components

The deployed Compose stack contains:

- `nginx`
- `app`
- `sso-proxy`
- `scheduler`
- `worker-chat`
- `worker-siem`
- `worker-batch`
- `redis`
- `ollama`

Optional:

- `worker-gpu` through the `gpu` profile

## AD, DNS, and Kerberos Prerequisites

Before you start, prepare:

- the AD DNS domain, for example `example.local`
- the LDAP server hostname
- the Kerberos KDC hostname if it is different from LDAP
- the Kerberos realm
- the base DN, for example `dc=example,dc=local`
- network connectivity from the VM to the AD and KDC hosts
- if SSO will be enabled:
  - the real HTTPS FQDN users will open in the browser
  - a matching `HTTP/<fqdn>@REALM` SPN
  - an HTTP service keytab for that SPN
  - a trusted TLS certificate for the real FQDN
  - domain-joined browsers configured to allow Negotiate/Kerberos for that FQDN

Important current implementation note:

- the runtime depends on hostnames, not raw IP addresses, for Kerberos/LDAP interoperability
- the repository also supports an installer-managed AD host IP override when container DNS is not sufficient

If you use the installer and provide an AD IP override, it may generate an installer-managed `docker-compose.override.yml`.

## Environment Configuration

The repository ships [.env.example](../.env.example) as a template. The real deployment uses `.env`.

Key environment groups include:

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
  - `SSO_LOGIN_PATH`
  - `SSO_SERVICE_PRINCIPAL`
  - `SSO_KEYTAB_PATH`
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

The installer writes `.env` for you. Manual operators should start from `.env.example`.

Model access examples for a pilot AD deployment might look like:

```dotenv
MODEL_ACCESS_CODING_GROUPS=AI_Users
MODEL_ACCESS_ADMIN_GROUPS=AI_Admins
```

These are only examples. The runtime does not hardcode those group names.

## Preferred Installation Path: `install.sh`

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
chmod +x install.sh
./install.sh
```

Replace `<repo-url>` with the actual repository URL after publication.

Optional explicit mode selection:

```bash
INSTALL_MODE=cpu ./install.sh
INSTALL_MODE=gpu ./install.sh
```

### What the installer actually does

`install.sh` currently:

1. validates the OS and privilege model
2. runs a system audit and prints a summary of:
   - OS, hostname, IP addresses
   - CPU, core count, RAM, free disk
   - Docker / Compose presence
   - outbound connectivity probes for Docker download, Docker registry, Ollama, and PyPI
   - GPU signals such as `nvidia-smi`, `lspci`, Docker GPU runtime visibility, and whether the `gpu` Compose profile exists
3. recommends `cpu` or `gpu` installation mode and asks for confirmation in interactive mode
4. warns about low resources and unknown checks, and fails early on critical outbound connectivity problems
5. installs Docker Engine and the Compose plugin if needed
6. installs Kerberos/LDAP-related host packages
7. installs the Ollama CLI if needed
8. re-validates GPU prerequisites after Docker is available:
   - if GPU mode is selected and prerequisites are ready, it keeps GPU mode
   - if `INSTALL_MODE=auto`, it falls back to CPU when GPU prerequisites are incomplete
   - if `INSTALL_MODE=gpu` is requested explicitly and prerequisites are still incomplete, it stops instead of continuing blindly
9. prompts for:
   - AD domain
   - LDAP host
   - optional separate Kerberos KDC host
   - base DN
   - optional AD test user for smoke validation
   - optional AD IP override
   - optional comma-separated AD groups for `coding` model access
   - optional comma-separated AD groups for `admin` model access
   - whether trusted reverse-proxy AD SSO should be enabled
   - if SSO is enabled:
     - the HTTP service principal, for example `HTTP/assistant.example.local@EXAMPLE.LOCAL`
     - the in-container keytab path, which must stay under `/etc/corporate-ai-sso/`
   - Redis password
   - JWT secret
10. validates that the LDAP/KDC hostnames resolve on the host, unless an explicit AD IP override was provided
11. if SSO is enabled, validates that the required HTTP service keytab is present under `deploy/sso/`
12. writes `.env`, including `GPU_ENABLED=true|false`, exact-match model access group mappings, and SSO-related flags
13. writes `deploy/krb5.conf`
14. optionally writes installer-managed `docker-compose.override.yml`
15. ensures the host-side Ollama model directory exists
16. generates self-signed TLS material in `deploy/certs/` if missing
17. starts the stack in the selected mode:
   - CPU mode: standard `docker compose ...`
   - GPU mode: `docker compose --profile gpu ...`
18. runs model bootstrap through [`bootstrap_ollama_models.sh`](../bootstrap_ollama_models.sh)
19. waits for `https://127.0.0.1/health/ready`
20. optionally runs an auth smoke check if a test account was provided

### What the installer does not automate

- NVIDIA driver installation
- NVIDIA container runtime setup
- trusted TLS certificate issuance
- AD topology discovery
- discovery of the correct AD groups for model-access categories
- generation of SPNs or service keytabs
- browser intranet/trusted-zone configuration for Kerberos SSO
- repair of non-installer-managed `docker-compose.override.yml`

If a GPU is detected but the GPU runtime is incomplete, the installer will not try to fix the host automatically. It will either fall back to CPU mode or stop, depending on how the installation mode was requested.

## Manual Installation

Use the manual path only if the installer cannot be used in your environment.

### 1. Clone the repository

```bash
git clone <repo-url> ai_agent_v1.1
cd ai_agent_v1.1
```

### 2. Install host prerequisites

At minimum, the current documentation and installer indicate these packages are expected on the host:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git gnupg jq lsb-release openssl \
  python3 python3-venv python3-pip krb5-user libsasl2-modules-gssapi-mit ldap-utils
```

Then install:

- Docker Engine
- Docker Compose plugin
- Ollama CLI

### 3. Create the environment file

```bash
cp .env.example .env
chmod 600 .env
```

Populate `.env` with your real AD, Redis, JWT, and runtime values.

For CPU deployments, keep:

```dotenv
GPU_ENABLED=false
```

For GPU deployments, set:

```dotenv
GPU_ENABLED=true
```

only when the host already has working GPU container support and you intend to start the `gpu` profile.

If you want SSO, also set:

```dotenv
TRUSTED_AUTH_PROXY_ENABLED=true
SSO_ENABLED=true
SSO_LOGIN_PATH=/auth/sso/login
SSO_SERVICE_PRINCIPAL=HTTP/assistant.example.local@EXAMPLE.LOCAL
SSO_KEYTAB_PATH=/etc/corporate-ai-sso/http.keytab
MODEL_ACCESS_CODING_GROUPS=AI_Users
MODEL_ACCESS_ADMIN_GROUPS=AI_Admins
```

These group names are only examples for a pilot environment. Replace them with your real AD groups.

### 4. Prepare Kerberos configuration

The runtime expects `deploy/krb5.conf`.

Create or update it to match your domain:

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

### 5. Prepare SSO keytab material if SSO is enabled

Create the directory and place the HTTP service keytab there:

```bash
mkdir -p deploy/sso
chmod 700 deploy/sso
install -m 600 /path/to/http.keytab deploy/sso/http.keytab
```

The keytab filename must match the basename used in `SSO_KEYTAB_PATH`. With the default value, the expected file is `deploy/sso/http.keytab`.

### 6. Prepare TLS certificates

The application is designed to run behind Nginx. The current repository uses:

- `deploy/certs/server.crt`
- `deploy/certs/server.key`

For local or pilot use, you can create self-signed material:

```bash
mkdir -p deploy/certs
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout deploy/certs/server.key \
  -out deploy/certs/server.crt
```

### 7. Start the stack

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

Use GPU mode only when:

- `GPU_ENABLED=true` is set in `.env`
- the host has working NVIDIA drivers
- Docker has working GPU runtime access

## Model Bootstrap

The application depends on at least one Ollama model being available.

The installer already tries to bootstrap models. Manual operators can run:

```bash
./bootstrap_ollama_models.sh
```

Useful checks:

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
docker compose exec -T ollama ollama pull gemma2:2b
```

If no models are available, the stack may still start, but chat requests will fail with a model-unavailable condition.

## Start, Stop, and Restart

Start:

```bash
docker compose up -d
```

Rebuild and restart:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

## Health Verification

### Container state

```bash
docker compose ps
```

### Liveness and readiness

```bash
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

`/health/ready` is healthy only when the application can see:

- Redis
- a fresh scheduler heartbeat
- at least one working chat worker
- schedulable capacity for chat workloads

### Initial logs

```bash
docker compose logs --tail=100 app scheduler worker-chat nginx
```

## First Login

Open:

```text
https://<vm-ip>
```

Notes:

- the browser may warn about the self-signed certificate
- a valid AD account is required
- successful login redirects to `/chat`

## Install Troubleshooting Basics

For install-path failures caused by Docker/PyPI/Ollama reachability, host DNS, `/etc/resolv.conf`, `systemd-resolved`, or Docker/container DNS drift, use the dedicated network troubleshooting section in [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md).

### `health/ready` never becomes healthy

Check:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat ollama nginx
docker compose exec -T ollama ollama list
```

### Kerberos or LDAP setup fails

Check:

- hostname-based LDAP/KDC configuration
- `deploy/krb5.conf`
- DNS resolution from the host and containers
- optional AD IP override if container DNS is unreliable

### The model is missing

Check:

```bash
docker compose exec -T ollama ollama list
./bootstrap_ollama_models.sh
```

### GPU profile does not start

This usually means host GPU container support is incomplete. The CPU deployment path remains the baseline supported mode.

## Related Documents

- [README.md](../README.md)
- [Architecture](ARCHITECTURE_en.md)
- [Administration and Operations](ADMIN_en.md)
- [Troubleshooting](TROUBLESHOOTING_en.md)
- [Security Baseline](SECURITY_en.md)

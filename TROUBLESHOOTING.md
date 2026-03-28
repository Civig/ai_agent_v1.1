# Troubleshooting

This document lists the most common deployment and runtime issues for Corporate AI Assistant.

## Deployment Checks

Start with:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat nginx
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

## `health/ready` is not `200`

Check:

- Redis is healthy
- the scheduler heartbeat is fresh
- at least one worker is healthy
- Ollama is available
- the default model exists in Ollama

Useful commands:

```bash
docker compose ps
docker compose logs --tail=100 redis scheduler worker-chat ollama app
docker compose exec -T ollama ollama list
```

## Kerberos / LDAP Fails With `No worthy mechs found`

Typical causes:

- missing `libsasl2-modules-gssapi-mit`
- LDAP server configured as an IP instead of a hostname
- incorrect `deploy/krb5.conf`
- DNS resolution mismatch inside containers

Check:

```bash
docker compose exec -T app bash -lc 'klist || true'
docker compose exec -T app bash -lc 'cat /etc/krb5.conf'
docker compose exec -T app bash -lc 'getent hosts <ldap-hostname>'
```

If container DNS cannot resolve the AD host, rerun `install.sh` and provide the optional AD IP override so it can generate an installer-managed `docker-compose.override.yml`.

## Nginx Fails to Start

Check:

- `deploy/nginx.conf` exists and is valid
- `deploy/certs/server.crt` and `deploy/certs/server.key` exist

Commands:

```bash
docker compose logs --tail=100 nginx
docker compose exec -T nginx nginx -t
```

## The Login Page Loads but Authentication Fails

Check:

- AD credentials are valid
- KDC is reachable from the VM
- LDAP / Kerberos settings in `.env` match the real domain
- the smoke-test user can authenticate manually

Commands:

```bash
docker compose logs --tail=100 app
```

## Models Do Not Appear in the UI

The model selector is driven by Ollama's live model catalog. If a model is not listed in the UI, it is usually not present in the Ollama runtime.

```bash
docker compose exec -T ollama ollama list
docker compose exec -T ollama ollama pull phi3:mini
```

## A Chat Job Stays Queued

Check:

- worker heartbeats are present
- `/health/ready` is healthy
- the current target has schedulable capacity
- the selected model is available in Ollama

Commands:

```bash
docker compose logs --tail=100 scheduler worker-chat app
```

## Redis Authentication Errors

Check that `.env` and `docker-compose.yml` use the same `REDIS_PASSWORD`, then recreate the stack:

```bash
docker compose up -d --build
```

## The Browser Warns About TLS

The default installer generates a self-signed certificate. This is expected for first-run deployments. Replace `deploy/certs/` with a trusted certificate before production exposure.

## Cleanup and Restart

Restart the stack:

```bash
docker compose up -d --build
```

Use the repository cleanup helper:

```bash
./clean.sh
```

The cleanup script is limited to project-generated resources and does not uninstall Docker or delete the repository.

# Troubleshooting

This root file is a short triage entrypoint. Full diagnostics and recovery steps live in the dedicated troubleshooting documents under `docs/`.

## First Checks

Start with:

```bash
docker compose ps
docker compose logs --tail=100 app scheduler worker-chat nginx
curl -k -fsS https://127.0.0.1/health/live
curl -k -fsS https://127.0.0.1/health/ready
```

## Full Troubleshooting Guides

- [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) - primary full troubleshooting reference
- [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md) - synced English companion

## Common Jump Points

- login, Kerberos, or LDAP issues -> [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- `/health/ready` unhealthy -> [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- missing models, file upload, or PDF parsing issues -> [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)
- queue, worker, or GPU issues -> [docs/TROUBLESHOOTING_ru.md](docs/TROUBLESHOOTING_ru.md) / [docs/TROUBLESHOOTING_en.md](docs/TROUBLESHOOTING_en.md)

For document roles and reading order, see [docs/INDEX.md](docs/INDEX.md).

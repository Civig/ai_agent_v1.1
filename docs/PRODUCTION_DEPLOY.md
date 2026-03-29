# Production Deployment Guide

This guide covers production-specific deployment deltas for Corporate AI Assistant.
Read it after the standard installation documents. Full installation steps live in [INSTALL_ru.md](INSTALL_ru.md) and [INSTALL_en.md](INSTALL_en.md). Routine day-2 operations live in [ADMIN_ru.md](ADMIN_ru.md) and [ADMIN_en.md](ADMIN_en.md).

## Target Environment

- Ubuntu 20.04+ or Debian 11+
- 4 CPU cores minimum, 8 recommended
- 8 GB RAM minimum, 16 GB recommended
- 40-50 GB free disk
- Access to Active Directory / Kerberos infrastructure

## What This Guide Covers

- production-specific differences from the standard install path
- TLS, FQDN, firewall, and exposure expectations
- hardening-oriented rollout checks before production use
- cross-references to the primary install, security, admin, and troubleshooting docs

## What This Guide Does Not Cover

- full installer walkthrough
- full manual installation runbook
- routine service lifecycle commands
- full incident diagnostics and recovery

## Standard Deployment Baseline

The supported deployment baseline remains Linux VM + Docker Compose + `install.sh`.
Use [INSTALL_ru.md](INSTALL_ru.md) or [INSTALL_en.md](INSTALL_en.md) for the supported installation path, installer behavior, and manual installation fallback.

## Production Prerequisites And Deltas

- use a real HTTPS FQDN, not only a lab IP
- replace installer-generated self-signed TLS with organization-approved certificate material
- confirm AD, DNS, and SPN consistency for the hostname profile you actually publish
- if SSO is planned, prepare the real `HTTP/<fqdn>@REALM` SPN and service keytab before enabling it
- keep `.env` only on the deployment host and rotate `SECRET_KEY` and `REDIS_PASSWORD`
- plan monitoring, log forwarding, backup, and host-access controls according to your environment
- keep Redis on the internal Compose network; do not expose Redis or the FastAPI container directly

## Production Rollout Checklist

1. Complete the standard install through [INSTALL_ru.md](INSTALL_ru.md) or [INSTALL_en.md](INSTALL_en.md).
2. Replace the contents of `deploy/certs/` with trusted TLS material for the real FQDN.
3. Verify AD hostname, DNS, and SPN alignment for LDAP and any planned SSO path.
4. Confirm only the intended public ports are exposed and that Redis remains internal-only.
5. Verify `https://<fqdn>/health/live` and `https://<fqdn>/health/ready`, login, and model availability.
6. Hand off routine operations to [ADMIN_ru.md](ADMIN_ru.md) / [ADMIN_en.md](ADMIN_en.md) and incident handling to [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md) / [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md).

## TLS And FQDN

The standard install path can generate self-signed certificates for internal smoke validation. That is not the recommended production posture. For production use, publish the service on the real FQDN and replace `deploy/certs/` with organization-approved TLS material.

## Network Exposure And Firewall

Expose only:

- `80/tcp`
- `443/tcp`

The application container itself should not be exposed directly.

## Hardening And Operations References

- [SECURITY.md](../SECURITY.md) - repository-level vulnerability reporting entrypoint
- [SECURITY_ru.md](SECURITY_ru.md) / [SECURITY_en.md](SECURITY_en.md) - product security baseline and operator-owned controls
- [ADMIN_ru.md](ADMIN_ru.md) / [ADMIN_en.md](ADMIN_en.md) - routine operations and maintenance
- [TROUBLESHOOTING_ru.md](TROUBLESHOOTING_ru.md) / [TROUBLESHOOTING_en.md](TROUBLESHOOTING_en.md) - full diagnostics and recovery

## Related Documents

- [../README.md](../README.md)
- [INSTALL_ru.md](INSTALL_ru.md)
- [INSTALL_en.md](INSTALL_en.md)
- [INDEX.md](INDEX.md)

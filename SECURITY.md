# Security Policy

## Supported Scope

This repository is intended for internal enterprise deployment. The public repository includes deployment automation, but operators are responsible for providing:

- organization-approved TLS certificates
- secure Active Directory / Kerberos connectivity
- secret rotation practices
- VM and Docker host hardening

## Reporting a Vulnerability

Please do not publish sensitive security findings as a public issue with exploit details.

If GitHub private vulnerability reporting is enabled for the repository, use that channel. Otherwise, contact the repository owner directly through the contact method listed on GitHub and share:

- a clear description of the issue
- impact and affected components
- reproduction steps
- suggested remediation, if available

## Security Expectations

Before production use, verify the following:

- `SECRET_KEY` is unique and strong
- `REDIS_PASSWORD` is rotated and stored securely
- `.env` is present only on the deployment host
- TLS material in `deploy/certs/` is either consciously self-signed for internal validation or replaced with a trusted certificate before production exposure
- the VM exposes only `80/tcp` and `443/tcp`
- Redis is reachable only on the internal Compose network
- `DEBUG_LOAD_ENABLED=false`
- Kerberos and LDAP point to real hostnames, not raw IPs
- the LDAP hostname matches the registered Kerberos SPN used by the directory service
- if a short LDAP hostname is used, the working SPN must match that short hostname

## What the Repository Already Does

- excludes `.env`, generated certificates, keytabs, logs, installer artifacts, models, and caches from Git
- disables debug load generation by default
- uses Redis-backed token revocation for logout
- protects login with Redis-backed rate limiting
- keeps the application behind Nginx in the default deployment model
- uses fail-closed LDAP handling in the runtime authentication path

## Operational Recommendations

- replace self-signed TLS with a trusted certificate before production use
- restrict SSH and management access by IP
- run the VM in a segmented internal network
- forward logs to a central system
- monitor `/health/ready`, Redis, Ollama, and container health states
- back up configuration and persistent volumes as required by your environment
- keep installer-managed `extra_hosts` aligned with the real AD IP if your internal DNS path is not fully deterministic
- validate the FQDN-specific LDAP SPN on the AD side before switching from a short hostname profile to the FQDN profile

## Kerberos and SPN Note

Kerberos service tickets are issued for a specific service principal name. For LDAP / GSSAPI to work reliably, the hostname used by the runtime must match the SPN registered in Active Directory.

The currently validated runtime profile is:

- use hostnames, not raw IP addresses, for `LDAP_SERVER` and `KERBEROS_KDC`
- keep the LDAP hostname aligned with the SPN registered in Active Directory
- use short hostname or FQDN only when DNS and SPN are consistent for that choice

If the runtime uses an FQDN before the matching `ldap/<fqdn>` SPN is properly registered and resolvable in the same way, LDAP authentication can fail even when `kinit` is successful.

## Known Operational Limits

- Redis is single-node by default
- the repository is prepared for future HA work, but does not ship Redis Sentinel out of the box
- CPU-only deployments will have lower throughput and higher latency
- large models may require manual capacity tuning for specific hardware profiles

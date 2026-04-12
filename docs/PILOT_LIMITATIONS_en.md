# Known Pilot Limitations

## Purpose

This document fixes the limitations that must be stated honestly before the pilot starts.

## Validation boundaries

- the earlier pilot package was pinned to `3396058`; it remains a historical pilot reference and not the current `v1.2.0` release-candidate baseline
- the GPU path is not proven without separately completing the [GPU validation playbook](GPU_VALIDATION_PLAYBOOK_en.md)
- trusted reverse-proxy SSO is not proven without separate validation on the real FQDN/SPN/keytab path

## Dashboard and access model

- the operator dashboard is implemented, but its access model remains a narrow temporary operator gate
- the dashboard must not be described as a production-ready RBAC surface
- the dashboard exposes telemetry/history/events and must remain operator-only
- honest `no-data` / `unavailable` states are correct behavior, not a UI defect by themselves

## Security posture limitations

- the installer generates self-signed TLS by default; that is acceptable for an internal pilot, but not sufficient for a production posture
- an external secret manager is not integrated
- centralized SIEM export is not implemented as a confirmed product capability
- model access uses env-driven group mapping and a policy catalog, not a full enterprise role model
- logout does not mean a global logout from Windows/Kerberos/browser SPNEGO state

## Reliability and platform limitations

- Redis is single-node by default
- HA Redis and an HA control plane are not present
- a packaged external observability stack is not shipped
- the dashboard remains a read-only monitoring surface and does not provide control actions

## Persistence limitations

- conversation storage ownership remains transitional between Redis and PostgreSQL
- the final authoritative PostgreSQL cutover for conversation data is not declared complete yet
- durable user/quota/audit entities are not finished as a final platform layer

## File-processing limitations

- file-chat is limited to the supported file types: `txt`, `pdf`, `docx`, `png`, `jpg`, `jpeg`
- a durable attachment platform is not implemented
- antivirus, sandbox execution, deep file-signature verification, and DLP are not implemented

## GPU-specific limitations

- the presence of the `worker-gpu` profile does not by itself prove real GPU usage
- silent CPU fallback must be checked separately through logs and host-side GPU evidence
- the dashboard must report GPU telemetry honestly; missing data must not be masked as “GPU OK”

## What must not be promised to the customer

The following items must not be promised as already proven:

- enterprise SSO readiness
- GPU readiness
- HA
- secret-manager integration
- DLP / malware scanning
- centralized observability / SIEM export
- production-ready dashboard RBAC

## Related documents

- [PILOT_SCOPE_en.md](PILOT_SCOPE_en.md)
- [PILOT_ACCEPTANCE_CHECKLIST_en.md](PILOT_ACCEPTANCE_CHECKLIST_en.md)
- [GPU_VALIDATION_PLAYBOOK_en.md](GPU_VALIDATION_PLAYBOOK_en.md)

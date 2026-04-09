# Pilot Acceptance Checklist

## Usage rule

The pilot is successful only when every applicable item below is closed as `yes` or `N/A by agreed scope`.

## Checklist

- [ ] The exact baseline SHA `33960581772787b162a0885bc2181f650f22a168` is deployed
- [ ] The supported install path was used: Linux VM + Docker Compose + `install.sh`
- [ ] Installation completed without a critical install blocker
- [ ] `.env` contains no placeholder secrets and no unagreed manual drift overrides
- [ ] `docker compose ps` shows the baseline stack as healthy/started
- [ ] `https://<host>/health/live` and `https://<host>/health/ready` return healthy status
- [ ] Password login with a valid AD account works
- [ ] At least one working Ollama model is available
- [ ] Normal chat completes successfully
- [ ] File-chat completes successfully on a supported file
- [ ] `/admin/dashboard` opens for the operator path and summary/live/history/events behave correctly
- [ ] If GPU is in pilot scope: the playbook in [GPU_VALIDATION_PLAYBOOK_en.md](GPU_VALIDATION_PLAYBOOK_en.md) finishes with verdict `validated`
- [ ] If SSO is in pilot scope: separate real-infrastructure evidence exists showing SSO validated on the real FQDN/SPN/keytab path
- [ ] The known limitations in [PILOT_LIMITATIONS_en.md](PILOT_LIMITATIONS_en.md) are formally accepted and are not disputed later as blocker surprises
- [ ] No open critical blocker remains for the agreed pilot scope

## Acceptance note

The GPU and SSO items cannot be treated as closed automatically only because the corresponding code or env flags exist in the repository.

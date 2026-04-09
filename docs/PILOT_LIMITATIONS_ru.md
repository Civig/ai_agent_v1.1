# Известные ограничения пилота

## Назначение

Этот документ фиксирует ограничения, которые должны быть честно проговорены до старта пилота.

## Границы валидации

- exact current HEAD `3396058` остаётся pilot baseline candidate и требует отдельной fresh install re-validation перед pilot freeze
- GPU path не считается доказанным без отдельного прохождения [GPU validation playbook](GPU_VALIDATION_PLAYBOOK_ru.md)
- trusted reverse-proxy SSO не считается доказанным без отдельной validation на реальном FQDN/SPN/keytab path

## Dashboard и модель доступа

- operator dashboard уже реализован, но его access model остаётся временным узким operator gate
- dashboard не должен описываться как production-ready RBAC surface
- dashboard раскрывает telemetry/history/events и должен оставаться operator-only
- honest `no-data` / `unavailable` состояния являются корректным поведением, а не UI defect сами по себе

## Ограничения текущего профиля безопасности

- installer по умолчанию генерирует self-signed TLS; для internal pilot это допустимо, для production posture этого недостаточно
- external secret manager не интегрирован
- централизованный SIEM export не реализован как confirmed product capability
- model access использует env-driven group mapping и policy catalog, а не full enterprise role model
- logout не означает глобальный logout из Windows/Kerberos/browser SPNEGO state

## Ограничения платформы и отказоустойчивости

- Redis по умолчанию single-node
- HA Redis и HA control plane отсутствуют
- packaged external observability stack не поставляется
- dashboard остаётся read-only monitoring surface и не даёт control actions

## Ограничения слоя хранения

- conversation storage ownership остаётся transitional между Redis и PostgreSQL
- финальный authoritative cutover conversation data на PostgreSQL ещё не объявлен завершённым
- durable user/quota/audit entities не доведены до финальной platform form

## Ограничения обработки файлов

- file-chat ограничен поддерживаемыми типами файлов: `txt`, `pdf`, `docx`, `png`, `jpg`, `jpeg`
- durable attachment platform не реализована
- antivirus, sandbox execution, deep file-signature verification и DLP не реализованы

## Ограничения GPU-сценария

- наличие `worker-gpu` profile само по себе не доказывает реальное использование GPU
- silent CPU fallback необходимо проверять отдельно по логам и host-side GPU evidence
- dashboard обязан показывать GPU telemetry честно; отсутствие данных не должно маскироваться под “GPU OK”

## Что нельзя обещать клиенту

Нельзя обещать как уже доказанное:

- enterprise SSO readiness
- GPU readiness
- HA
- secret-manager integration
- DLP / malware scanning
- centralized observability / SIEM export
- production-ready dashboard RBAC

## Связанные документы

- [PILOT_SCOPE_ru.md](PILOT_SCOPE_ru.md)
- [PILOT_ACCEPTANCE_CHECKLIST_ru.md](PILOT_ACCEPTANCE_CHECKLIST_ru.md)
- [GPU_VALIDATION_PLAYBOOK_ru.md](GPU_VALIDATION_PLAYBOOK_ru.md)

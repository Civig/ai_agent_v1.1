# Чек-лист приёмки пилота

## Правило использования

Пилот считается успешным только если каждый применимый пункт ниже закрыт как `да` или `N/A по согласованному scope`.

## Чек-лист

- [ ] Развёрнут agreed exact baseline SHA для текущего validation cycle
- [ ] Использован supported install path: Linux VM + Docker Compose + `install.sh`
- [ ] Установка завершилась без critical install blocker
- [ ] В `.env` нет placeholder secrets и нет несогласованных manual drift overrides
- [ ] `docker compose ps` показывает healthy/started baseline stack
- [ ] `https://<host>/health/live` и `https://<host>/health/ready` возвращают healthy status
- [ ] Password login под валидным AD account работает
- [ ] Доступна хотя бы одна рабочая Ollama model
- [ ] Обычный chat успешно выполняется
- [ ] File-chat успешно выполняется на поддерживаемом файле
- [ ] `/admin/dashboard` открывается для operator path и summary/live/history/events ведут себя корректно
- [ ] Если GPU входит в pilot scope: playbook из [GPU_VALIDATION_PLAYBOOK_ru.md](GPU_VALIDATION_PLAYBOOK_ru.md) завершён с verdict `validated`
- [ ] Если SSO входит в pilot scope: есть отдельное real-infra evidence, что SSO validated на реальном FQDN/SPN/keytab path
- [ ] Known limitations из [PILOT_LIMITATIONS_ru.md](PILOT_LIMITATIONS_ru.md) формально приняты и не оспариваются как blocker surprise
- [ ] Не осталось ни одного открытого critical blocker для agreed pilot scope

## Примечание по приёмке

Пункты GPU и SSO не могут считаться автоматически закрытыми только потому, что соответствующий код или env flags присутствуют в репозитории.

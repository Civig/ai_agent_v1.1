# Supported OS Matrix

This file is the canonical supported operating-system matrix for Corporate AI Assistant `ai_agent_v1.1`.
Этот файл — canonical matrix поддерживаемых операционных систем для Corporate AI Assistant `ai_agent_v1.1`.

Russian operator docs remain the primary reference. This matrix is intentionally bilingual because it is meant to support operator, implementation, and presale discussions without creating two competing sources of truth.
Русские operator docs остаются основными, но эта матрица намеренно сделана двуязычной, чтобы не создавать два конкурирующих источника истины для внедрений и presale-коммуникации.

## Purpose And Scope

Use this matrix to answer four different questions:

- which operating systems have recorded validation evidence for the current release family
- which operating systems remain supported targets by installer and packaging assumptions, but were not re-validated on the current HEAD
- which platforms are only best effort / not validated
- which platforms are unsupported

Используйте эту матрицу, чтобы отделять:

- recorded validation evidence for the current release family
- supported target, but not re-validated on the current HEAD
- best effort / not validated
- unsupported

## Validation Semantics

- `Validated reference point`:
  A concrete OS/version was validated on a recorded baseline revision in the current release family. Re-validation is still recommended before freezing a new pilot baseline on a newer HEAD.
  Конкретная ОС/версия была валидирована на зафиксированной revision внутри текущего release family. Перед фиксацией нового pilot baseline на более свежем HEAD рекомендуется повторная валидация.
- `Supported target, not re-validated on current HEAD`:
  The current installer and packaging assumptions explicitly support this platform family or version range, but the current HEAD was not re-validated on every version in that range.
  Текущий installer и packaging assumptions явно поддерживают эту платформу или диапазон версий, но current HEAD не был повторно валидирован на каждой версии из этого диапазона.
- `Best effort / not validated`:
  The platform may be close enough to the supported packaging/runtime assumptions that it could work, but the repository does not validate it and does not promise official support.
  Платформа может оказаться совместимой с текущими packaging/runtime assumptions, но репозиторий её не валидирует и не обещает официальную поддержку.
- `Unsupported`:
  The current installer or platform assumptions reject the platform, or the project does not support it as a deployment target.
  Текущий installer или platform assumptions такую платформу отвергают, либо проект не поддерживает её как deployment target.

## Supported OS Matrix

| Platform | Current status | Evidence basis | Notes |
| --- | --- | --- | --- |
| Ubuntu 24.04 LTS | Validated reference point | `install.sh` supports Ubuntu `20.04+`; a clean installer validation was recorded successfully on Ubuntu 24.04 for revision `eba7ea9` | This is the clearest recorded validation point in the current release family, but current HEAD still needs fresh validation before a pilot freeze. |
| Ubuntu 22.04 LTS | Supported target, not re-validated on current HEAD | `install.sh` accepts Ubuntu `20.04+`; docs and installer are Ubuntu-aware | Supported by the current installer path, but not explicitly re-validated on current HEAD. |
| Ubuntu 20.04 LTS and newer Ubuntu LTS within the current installer range | Supported target, not re-validated on current HEAD | `install.sh` requires Ubuntu `20.04+`; docs currently describe Ubuntu `20.04+` as the supported host profile | Do not treat every version in this range as validated just because the installer accepts it. |
| Debian 11 and newer | Supported target, not re-validated on current HEAD | `install.sh` explicitly accepts Debian `11+`; docs and package assumptions include Debian `11+` | Debian is a supported installer target, but current HEAD was not re-validated on every Debian version. |
| Debian-family derivatives | Best effort / not validated | Some derivatives may be close to the current Debian/Ubuntu `apt`-based assumptions | No official support promise. Some derivatives may still be rejected by `install.sh` depending on `/etc/os-release` identifiers and repository assumptions. |
| RHEL / Rocky / Alma family | Unsupported | `install.sh` rejects non-Ubuntu/non-Debian OS IDs; no `dnf`/`yum` install path exists | Do not position these distributions as supported. |
| Fedora | Unsupported | `install.sh` rejects non-Ubuntu/non-Debian OS IDs; no `dnf` path exists | Not a supported deployment target. |
| openSUSE / SUSE | Unsupported | `install.sh` rejects non-Ubuntu/non-Debian OS IDs; no `zypper` path exists | Not a supported deployment target. |
| Arch / rolling distributions | Unsupported | `install.sh` rejects non-Ubuntu/non-Debian OS IDs; packaging assumptions are not rolling-release oriented | Not a supported deployment target. |
| Non-Linux operating systems | Unsupported | `install.sh` supports Linux only; legacy Windows helper files are not the validated release baseline | Windows/macOS are not supported deployment targets for the current baseline. |

## Notes And Evidence Boundaries

- The current installer supports Linux only and explicitly accepts only `ubuntu` and `debian` OS IDs from `/etc/os-release`.
- The current install path is `apt` / `dpkg` based. That is a strong compatibility signal for Ubuntu and Debian, and a strong incompatibility signal for non-`apt` families.
- The most recent recorded clean installer validation evidence in this repository is Ubuntu 24.04 for revision `eba7ea9`.
- That recorded evidence does not automatically upgrade Ubuntu 22.04, the whole Ubuntu `20.04+` range, or Debian `11+` to `validated`.
- The exact current HEAD should still be re-validated before a new pilot baseline is frozen.
- GPU and SSO require additional runtime/infrastructure validation even on an otherwise supported OS.
- Future validation runs may expand the validated set. Until then, this matrix should stay conservative.

## Procurement And Deployment Interpretation

- For the safest current recommendation, position Ubuntu 24.04 LTS as the primary recorded validation point and re-validate the current HEAD before a pilot freeze.
- For implementation planning, Ubuntu `20.04+` and Debian `11+` remain supported installer targets, but avoid presenting every version in those ranges as re-validated on the current HEAD.
- For presale and customer qualification, treat Debian-family derivatives as best effort only unless and until they are explicitly validated.
- Do not promise support for RHEL-family, Fedora, openSUSE/SUSE, Arch, or non-Linux deployment targets on the current baseline.

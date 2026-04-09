#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = (
    "install_name",
    "installer_display_name",
    "installer_summary",
    "installer_cpu_guidance",
    "installer_min_ram_gb",
    "installer_rec_ram_gb",
    "installer_gpu_guidance",
    "installer_min_vram_gb",
    "installer_comment",
    "installer_source_hint",
)


def as_gb(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid size value")
    if isinstance(value, int):
        return f"{value} GB"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value)} GB"
        return f"{value:g} GB"
    raise ValueError(f"unsupported size value: {value!r}")


def load_registry(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Installer model registry is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Installer model registry is invalid JSON: {path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise SystemExit("Installer model registry must contain a top-level 'models' array")

    return payload


def installer_models(payload: dict) -> list[dict]:
    models = [model for model in payload["models"] if model.get("enabled_in_installer") is True]
    if not models:
        raise SystemExit("Installer model registry does not contain any enabled installer models")
    return sorted(
        models,
        key=lambda model: (
            int(model.get("installer_order", 10**9)),
            str(model.get("install_name", "")),
        ),
    )


def validate_model(model: dict) -> None:
    model_key = str(model.get("install_name") or model.get("id") or "unknown-model")
    missing = [field for field in REQUIRED_FIELDS if field not in model]
    if missing:
        raise SystemExit(f"Installer-enabled model '{model_key}' is missing required fields: {', '.join(missing)}")


def emit_records(models: list[dict]) -> None:
    for model in models:
        validate_model(model)
        record = [
            str(model["install_name"]).strip(),
            str(model["installer_display_name"]).strip(),
            str(model["installer_summary"]).strip(),
            str(model["installer_cpu_guidance"]).strip(),
            as_gb(model["installer_min_ram_gb"]),
            as_gb(model["installer_rec_ram_gb"]),
            str(model["installer_gpu_guidance"]).strip(),
            as_gb(model["installer_min_vram_gb"]),
            str(model["installer_comment"]).strip(),
            str(model["installer_source_hint"]).strip(),
        ]
        if not all(record):
            raise SystemExit(f"Installer-enabled model '{model['install_name']}' contains an empty installer field")
        print("|".join(record))


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        raise SystemExit("Usage: export_installer_model_catalog.py [registry-path]")

    registry_path = Path(argv[1]) if len(argv) == 2 else Path(__file__).resolve().parents[1] / "models" / "catalog.json"
    payload = load_registry(registry_path)
    emit_records(installer_models(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

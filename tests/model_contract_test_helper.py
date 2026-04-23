from __future__ import annotations

import subprocess
from pathlib import Path


def exported_canonical_default_model(repo_root: Path) -> str:
    result = subprocess.run(
        [
            "python3",
            str(repo_root / "tools" / "export_installer_model_catalog.py"),
            "--default-model",
            str(repo_root / "models" / "catalog.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

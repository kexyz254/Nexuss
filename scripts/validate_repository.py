"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Repository policy validation for the Nexuss confidential prototype.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "README.md",
    "CONFIDENTIALITY.md",
    "LICENSE",
    "SECURITY.md",
    "pyproject.toml",
    "contracts/openapi/core-api.yaml",
    "contracts/schemas/task-request.schema.json",
    "contracts/schemas/capability-result.schema.json",
    "contracts/schemas/action-receipt.schema.json",
    "docs/adr/ADR-0003-p1-core-simulator.md",
    "src/nexuss/api/app.py",
    "src/nexuss/core/service.py",
]

FORBIDDEN_NAMES = {
    ".env",
    "id_rsa",
    "credentials.json",
    "secrets.json",
}

FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}

IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
}

SCHEMAS = [
    "contracts/schemas/task-request.schema.json",
    "contracts/schemas/capability-result.schema.json",
    "contracts/schemas/action-receipt.schema.json",
]


def main() -> int:
    errors: list[str] = []

    for required_path in REQUIRED:
        if not (ROOT / required_path).is_file():
            errors.append(f"missing required file: {required_path}")

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(ROOT)

        if any(part in IGNORED_DIRECTORIES for part in relative_path.parts):
            continue

        if path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden secret-like file: {relative_path}")

        if path.suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden generated file: {relative_path}")

    for schema_path in SCHEMAS:
        try:
            json.loads((ROOT / schema_path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid JSON {schema_path}: {exc}")

    manifest = (ROOT / "FILE_MANIFEST.txt").read_text(encoding="utf-8")

    if "__pycache__" in manifest or ".pyc" in manifest or ".pyo" in manifest:
        errors.append("FILE_MANIFEST.txt contains generated Python artifacts")

    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
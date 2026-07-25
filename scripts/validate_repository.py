"""Repository policy validation for the Nexuss confidential prototype."""

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
]
FORBIDDEN_NAMES = {".env", "id_rsa", "credentials.json", "secrets.json"}


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")

    for path in ROOT.rglob("*"):
        if path.is_file() and path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden secret-like file: {path.relative_to(ROOT)}")

    for rel in [
        "contracts/schemas/task-request.schema.json",
        "contracts/schemas/capability-result.schema.json",
    ]:
        try:
            json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid JSON {rel}: {exc}")

    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

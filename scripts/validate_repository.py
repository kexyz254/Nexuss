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
    "contracts/schemas/approval-decision.schema.json",
    "docs/adr/ADR-0003-p1-core-simulator.md",
    "docs/adr/ADR-0004-ui-and-local-readonly-vertical-slice.md",
    "docs/adr/ADR-0005-approved-action-platform.md",
    "docs/requirements/p3-approved-action-platform-v0.1.md",
    "docs/security/p3-approved-actions-threat-model.md",
    "docs/adr/ADR-0006-trusted-device-mesh-and-phone-approval.md",
    "docs/requirements/p4-trusted-device-mesh-v0.1.md",
    "docs/security/p4-device-mesh-threat-model.md",
    "contracts/schemas/mobile-approval.schema.json",
    "contracts/schemas/device-command-envelope.schema.json",
    "src/nexuss/device/client.py",
    "src/nexuss/device/signing.py",
    "src/nexuss/device_node/app.py",
    "src/nexuss/device_node/executor.py",
    "src/nexuss/mobile/gateway.py",
    "src/nexuss/mobile/models.py",
    "src/nexuss/api/app.py",
    "src/nexuss/core/executor.py",
    "src/nexuss/core/managed_notes.py",
    "src/nexuss/core/registry.py",
    "src/nexuss/core/service.py",
    "src/nexuss/core/state_machine.py",
    "src/nexuss/ui/index.html",
    "src/nexuss/ui/app.js",
    "src/nexuss/ui/styles.css",
    "src/nexuss/ui/mobile.html",
    "src/nexuss/ui/mobile.js",
    "src/nexuss/ui/mobile.css",
    "scripts/start_p4.ps1",
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
    "contracts/schemas/approval-decision.schema.json",
    "contracts/schemas/mobile-approval.schema.json",
    "contracts/schemas/device-command-envelope.schema.json",
]


def main() -> int:
    errors: list[str] = []

    for required_path in REQUIRED:
        if not (ROOT / required_path).is_file():
            errors.append(f"missing required file: {required_path}")

    for candidate_path in ROOT.rglob("*"):
        if not candidate_path.is_file():
            continue

        relative_candidate = candidate_path.relative_to(ROOT)

        if any(part in IGNORED_DIRECTORIES for part in relative_candidate.parts):
            continue

        if candidate_path.name in FORBIDDEN_NAMES:
            errors.append(f"forbidden secret-like file: {relative_candidate}")

        if candidate_path.suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden generated file: {relative_candidate}")

    for schema_path in SCHEMAS:
        try:
            document = json.loads((ROOT / schema_path).read_text(encoding="utf-8"))
            if document.get("additionalProperties") is not False:
                errors.append(
                    "schema must fail closed with additionalProperties=false: "
                    f"{schema_path}"
                )
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

"""Atomic local persistence for engineering lifecycle outcomes."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.lifecycle import EngineeringLifecycleOutcome


class JsonEngineeringLifecycleStore:
    """Store secret-free lifecycle state for UI and recovery."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        outcome: EngineeringLifecycleOutcome,
    ) -> Path:
        path = self._path(outcome.task_id)
        payload = outcome.model_dump_json(indent=2)
        if outcome.credentials_exposed:
            raise EngineeringError(
                "ENGINEERING_RECEIPT_SECRET_EXPOSURE",
                "A lifecycle outcome marked as exposing credentials "
                "cannot be persisted.",
            )
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
        return path

    def load(
        self,
        task_id: UUID,
    ) -> EngineeringLifecycleOutcome | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        return EngineeringLifecycleOutcome.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def _path(self, task_id: UUID) -> Path:
        return self.root / f"{task_id}.json"

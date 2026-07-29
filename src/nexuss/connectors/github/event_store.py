"""Atomic local persistence for read-only GitHub workspace receipts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID

from nexuss.connectors.github.operation_models import ReadOnlyReceipt


class ReadOnlyReceiptStore:
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @classmethod
    def from_environment(cls) -> ReadOnlyReceiptStore:
        local_data = (
            os.getenv("LOCALAPPDATA")
            or os.getenv("XDG_DATA_HOME")
            or str(Path.home() / ".local" / "share")
        )
        return cls(Path(local_data) / "Nexuss" / "github-workspace" / "receipts")

    def put(self, receipt: ReadOnlyReceipt) -> Path:
        destination = self._path(receipt.receipt_id)
        temporary = destination.with_suffix(".tmp")
        encoded = json.dumps(
            receipt.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        with self._lock:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        return destination

    def get(self, receipt_id: UUID) -> ReadOnlyReceipt:
        path = self._path(receipt_id)
        with self._lock:
            payload = json.loads(path.read_text(encoding="utf-8"))
        return ReadOnlyReceipt.model_validate(payload)

    def list_recent(self, *, limit: int = 100) -> tuple[ReadOnlyReceipt, ...]:
        bounded = max(1, min(limit, 500))
        paths = sorted(
            self._root.glob("*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )[:bounded]
        receipts: list[ReadOnlyReceipt] = []
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                receipts.append(ReadOnlyReceipt.model_validate(payload))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return tuple(receipts)

    def _path(self, receipt_id: UUID) -> Path:
        return self._root / f"{receipt_id}.json"

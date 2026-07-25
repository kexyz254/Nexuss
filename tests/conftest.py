"""Isolate process-local Nexuss services for every automated test."""

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from nexuss.api import app as app_module
from nexuss.core.managed_notes import ManagedNoteStore
from nexuss.core.service import CoreSimulatorService


@pytest.fixture(autouse=True)
def isolate_nexuss_service(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    service = CoreSimulatorService(note_store=ManagedNoteStore(tmp_path / "managed"))
    monkeypatch.setattr(app_module, "service", service)

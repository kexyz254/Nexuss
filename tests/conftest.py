"""Isolate process-local Nexuss services for every automated test."""

from collections import defaultdict, deque
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from nexuss.api import app as app_module
from nexuss.core.managed_notes import ManagedNoteStore
from nexuss.core.service import CoreSimulatorService
from nexuss.memory.store import SqliteMemoryStore
from nexuss.mobile.gateway import MobileApprovalGateway
from tests.fakes import FakeDeviceNodeClient


@pytest.fixture
def fake_device_client() -> FakeDeviceNodeClient:
    return FakeDeviceNodeClient()


@pytest.fixture(autouse=True)
def isolate_nexuss_service(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    fake_device_client: FakeDeviceNodeClient,
) -> None:
    # The gateway is built first and injected, mirroring nexuss.api.app. Without
    # this the harness runs a service with no pairing gateway, so every device
    # capability fails closed under test while working in production.
    gateway = MobileApprovalGateway(mobile_url="http://testserver/mobile")
    service = CoreSimulatorService(
        note_store=ManagedNoteStore(tmp_path / "managed"),
        device_client=fake_device_client,
        pairing_gateway=gateway,
        memory_store=SqliteMemoryStore(tmp_path / "memory.db"),
    )
    monkeypatch.setattr(app_module, "service", service)
    monkeypatch.setattr(app_module, "mobile_gateway", gateway)

    # The pairing rate limiter is module-level and survives between tests, so
    # attempts accumulate across the whole session and later tests are refused
    # with 429 for something an earlier test did. Reset it with the rest of the
    # process-local state; the limiter itself has its own dedicated coverage.
    monkeypatch.setattr(app_module, "_pair_attempts", defaultdict(deque))

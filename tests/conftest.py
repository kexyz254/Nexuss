"""Isolate process-local Nexuss services for every automated test."""

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from nexuss.api import app as app_module
from nexuss.core.managed_notes import ManagedNoteStore
from nexuss.core.service import CoreSimulatorService
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
    service = CoreSimulatorService(
        note_store=ManagedNoteStore(tmp_path / "managed"),
        device_client=fake_device_client,
    )
    gateway = MobileApprovalGateway(mobile_url="http://testserver/mobile")
    monkeypatch.setattr(app_module, "service", service)
    monkeypatch.setattr(app_module, "mobile_gateway", gateway)

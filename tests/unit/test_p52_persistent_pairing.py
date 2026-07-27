"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Paired phones must survive a Core restart, and must still age out.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.mobile.gateway import MobileApprovalGateway, MobilePairingError
from nexuss.mobile.store import SqliteDeviceStore


def _pair(gateway: MobileApprovalGateway, session_id, label: str = "Primary phone"):
    challenge = gateway.create_pairing(session_id)
    return gateway.pair(challenge.pairing_code, label)


def test_paired_device_survives_a_gateway_restart(tmp_path: Path) -> None:
    database = tmp_path / "paired-devices.db"
    session_id = uuid4()

    first = MobileApprovalGateway(store=SqliteDeviceStore(database))
    device = _pair(first, session_id)

    # A new gateway over the same file stands in for a Core restart.
    second = MobileApprovalGateway(store=SqliteDeviceStore(database))

    assert second.authenticate(device.device_id, device.device_token) == session_id


def test_restart_does_not_persist_the_bearer_token(tmp_path: Path) -> None:
    database = tmp_path / "paired-devices.db"
    device = _pair(MobileApprovalGateway(store=SqliteDeviceStore(database)), uuid4())

    contents = database.read_bytes()

    assert device.device_token.encode("utf-8") not in contents


def test_contact_slides_the_expiry_window(tmp_path: Path) -> None:
    database = tmp_path / "paired-devices.db"
    gateway = MobileApprovalGateway(store=SqliteDeviceStore(database))
    device = _pair(gateway, uuid4())

    original = gateway.list_devices()[0].expires_at
    later = datetime.now(UTC) + timedelta(days=10)
    gateway.authenticate(device.device_id, device.device_token, now=later)

    assert gateway.list_devices()[0].expires_at > original


def test_an_abandoned_device_still_expires(tmp_path: Path) -> None:
    database = tmp_path / "paired-devices.db"
    gateway = MobileApprovalGateway(store=SqliteDeviceStore(database))
    device = _pair(gateway, uuid4())

    abandoned = datetime.now(UTC) + timedelta(days=31)

    with pytest.raises(MobilePairingError, match="MOBILE_DEVICE_SESSION_EXPIRED"):
        gateway.authenticate(device.device_id, device.device_token, now=abandoned)

    # Expiry must clear the durable record, not just the in-process one.
    assert MobileApprovalGateway(store=SqliteDeviceStore(database)).list_devices() == ()


def test_revoke_removes_the_device_permanently(tmp_path: Path) -> None:
    database = tmp_path / "paired-devices.db"
    gateway = MobileApprovalGateway(store=SqliteDeviceStore(database))
    device = _pair(gateway, uuid4())

    gateway.revoke(device.device_id)

    restarted = MobileApprovalGateway(store=SqliteDeviceStore(database))
    with pytest.raises(MobilePairingError, match="MOBILE_DEVICE_NOT_PAIRED"):
        restarted.authenticate(device.device_id, device.device_token)


def test_default_gateway_stores_nothing_on_disk() -> None:
    """The default store keeps the wider test suite hermetic."""
    gateway = MobileApprovalGateway()
    device = _pair(gateway, uuid4())

    assert MobileApprovalGateway().list_devices() == ()
    assert gateway.authenticate(device.device_id, device.device_token)

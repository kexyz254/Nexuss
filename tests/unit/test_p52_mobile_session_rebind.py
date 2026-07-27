"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from uuid import UUID, uuid4

from nexuss.mobile.gateway import MobileApprovalGateway


def _pair(gateway: MobileApprovalGateway, session_id: UUID) -> tuple[UUID, str]:
    challenge = gateway.create_pairing(session_id)
    session = gateway.pair(challenge.pairing_code, "Primary phone")
    return session.device_id, session.device_token


def test_rebind_moves_paired_device_to_the_current_desktop_session() -> None:
    gateway = MobileApprovalGateway()
    first_session = uuid4()
    second_session = uuid4()

    device_id, device_token = _pair(gateway, first_session)
    assert gateway.authenticate(device_id, device_token) == first_session

    paired, rebound = gateway.rebind_sessions(second_session)

    assert paired == 1
    assert rebound == 1
    assert gateway.authenticate(device_id, device_token) == second_session


def test_rebind_is_idempotent_for_devices_already_on_the_session() -> None:
    gateway = MobileApprovalGateway()
    session_id = uuid4()
    device_id, device_token = _pair(gateway, session_id)

    paired, rebound = gateway.rebind_sessions(session_id)

    assert paired == 1
    assert rebound == 0
    assert gateway.authenticate(device_id, device_token) == session_id


def test_rebind_preserves_the_device_token() -> None:
    """Rebinding must not force the phone through pairing again."""
    gateway = MobileApprovalGateway()
    device_id, device_token = _pair(gateway, uuid4())

    gateway.rebind_sessions(uuid4())

    assert gateway.authenticate(device_id, device_token)


def test_rebind_with_no_paired_devices_reports_zero() -> None:
    gateway = MobileApprovalGateway()

    paired, rebound = gateway.rebind_sessions(uuid4())

    assert paired == 0
    assert rebound == 0

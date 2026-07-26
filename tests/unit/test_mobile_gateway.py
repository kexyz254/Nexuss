"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nexuss.mobile.gateway import MobileApprovalGateway, MobilePairingError

SESSION_ID = UUID("00000000-0000-0000-0000-000000000750")
NOW = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)


def test_pairing_is_single_use_and_device_token_authenticates() -> None:
    gateway = MobileApprovalGateway(mobile_url="http://192.168.1.10:8100/mobile")
    challenge = gateway.create_pairing(SESSION_ID, now=NOW)
    paired = gateway.pair(challenge.pairing_code, "Android primary", now=NOW)

    assert gateway.authenticate(paired.device_id, paired.device_token, now=NOW) == SESSION_ID
    with pytest.raises(MobilePairingError, match="PAIRING_CODE_ALREADY_USED"):
        gateway.pair(challenge.pairing_code, "Second phone", now=NOW)


def test_expired_pairing_and_bad_tokens_fail_closed() -> None:
    gateway = MobileApprovalGateway()
    challenge = gateway.create_pairing(SESSION_ID, now=NOW)

    with pytest.raises(MobilePairingError, match="PAIRING_CODE_EXPIRED"):
        gateway.pair(challenge.pairing_code, "Phone", now=NOW + timedelta(minutes=11))

    fresh = gateway.create_pairing(SESSION_ID, now=NOW)
    paired = gateway.pair(fresh.pairing_code, "Phone", now=NOW)
    with pytest.raises(MobilePairingError, match="MOBILE_DEVICE_TOKEN_INVALID"):
        gateway.authenticate(paired.device_id, "wrong-token", now=NOW)

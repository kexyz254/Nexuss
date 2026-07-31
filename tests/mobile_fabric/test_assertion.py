"""P6.7A request assertion tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nexuss.mobile_fabric.assertion import (
    AssertionInput,
    DeviceAssertionVerifier,
    MobileAssertionError,
)


def test_assertion_verifies_once_and_rejects_replay() -> None:
    verifier = DeviceAssertionVerifier()
    assertion = AssertionInput(
        method="POST",
        path="/v1/mobile-fabric/signals",
        timestamp=datetime.now(UTC),
        nonce="n" * 32,
        body_sha256="a" * 64,
    )
    signature = verifier.sign("device-token-value", assertion)

    verifier.verify(
        device_token="device-token-value",
        assertion=assertion,
        signature=signature,
    )

    with pytest.raises(MobileAssertionError, match="MOBILE_ASSERTION_REPLAYED"):
        verifier.verify(
            device_token="device-token-value",
            assertion=assertion,
            signature=signature,
        )


def test_assertion_uses_android_compatible_utc_timestamp() -> None:
    assertion = AssertionInput(
        method="POST",
        path="/v1/mobile-fabric/signals",
        timestamp=datetime.fromisoformat("2026-07-31T10:00:00+00:00"),
        nonce="a" * 32,
        body_sha256="b" * 64,
    )

    lines = assertion.canonical().decode("utf-8").splitlines()

    assert lines[2] == "2026-07-31T10:00:00Z"

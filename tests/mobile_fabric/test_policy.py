"""P6.7A mobile policy tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nexuss.mobile_fabric.models import MobileSignal, MobileSignalKind, MobileSource
from nexuss.mobile_fabric.policy import MobilePolicy, MobilePolicyError


def test_whatsapp_notification_is_normalized_and_hashed() -> None:
    policy = MobilePolicy.default()
    signal = MobileSignal(
        source=MobileSource.WHATSAPP,
        package_name="com.whatsapp",
        kind=MobileSignalKind.MESSAGE_RECEIVED,
        occurred_at=datetime.now(UTC),
        sender_label="Amina",
        text="Can we meet at 3 PM?",
    )

    normalized = policy.normalize_signal(signal)

    assert normalized.source is MobileSource.WHATSAPP
    assert normalized.content_sha256 is not None
    assert normalized.sensitive is False


def test_otp_content_is_withheld() -> None:
    policy = MobilePolicy.default()
    signal = MobileSignal(
        source=MobileSource.SMS,
        package_name="com.google.android.apps.messaging",
        kind=MobileSignalKind.MESSAGE_RECEIVED,
        occurred_at=datetime.now(UTC),
        text="Your verification code is 123456",
    )

    normalized = policy.normalize_signal(signal)

    assert normalized.text == "[sensitive notification content withheld]"
    assert normalized.sensitive is True


def test_unknown_package_fails_closed() -> None:
    policy = MobilePolicy.default()
    signal = MobileSignal(
        source=MobileSource.OTHER,
        package_name="example.untrusted.app",
        kind=MobileSignalKind.APP_NOTIFICATION,
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(MobilePolicyError, match="MOBILE_PACKAGE_NOT_ALLOWLISTED"):
        policy.normalize_signal(signal)

"""Policy controls for trusted mobile communication access and actions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from nexuss.mobile_fabric.models import (
    MobileActionKind,
    MobileCapabilityEntry,
    MobileCapabilityMatrix,
    MobileCapabilityStatus,
    MobileSignal,
    MobileSource,
)

_DEFAULT_PACKAGES: dict[str, MobileSource] = {
    "com.whatsapp": MobileSource.WHATSAPP,
    "com.instagram.android": MobileSource.INSTAGRAM,
    "com.facebook.lite": MobileSource.FACEBOOK_LITE,
    "com.google.android.apps.messaging": MobileSource.SMS,
    "com.samsung.android.messaging": MobileSource.SMS,
    "com.google.android.dialer": MobileSource.PHONE,
    "com.samsung.android.dialer": MobileSource.PHONE,
    "ai.nexuss.companion": MobileSource.OTHER,
    "ai.nexuss.companion.debug": MobileSource.OTHER,
}

_SENSITIVE_PATTERN = re.compile(
    r"\b(?:otp|one[- ]time|verification|security|login|auth(?:entication)?)\b"
    r".{0,80}\b\d{4,8}\b",
    re.IGNORECASE | re.DOTALL,
)
_SECRET_PATTERN = re.compile(
    r"\b(?:password|passcode|recovery code|api key|access token|private key)\b",
    re.IGNORECASE,
)


class MobilePolicyError(ValueError):
    """Raised when mobile data or actions violate the declared boundary."""


@dataclass(frozen=True, slots=True)
class MobilePolicy:
    package_sources: dict[str, MobileSource]

    @classmethod
    def default(cls) -> MobilePolicy:
        return cls(package_sources=dict(_DEFAULT_PACKAGES))

    def source_for_package(self, package_name: str) -> MobileSource:
        try:
            return self.package_sources[package_name]
        except KeyError as exc:
            raise MobilePolicyError("MOBILE_PACKAGE_NOT_ALLOWLISTED") from exc

    def normalize_signal(self, signal: MobileSignal) -> MobileSignal:
        expected_source = self.source_for_package(signal.package_name)
        if signal.source is not expected_source:
            raise MobilePolicyError("MOBILE_SOURCE_PACKAGE_MISMATCH")

        text = signal.text
        sensitive = signal.sensitive
        if text and (_SENSITIVE_PATTERN.search(text) or _SECRET_PATTERN.search(text)):
            text = "[sensitive notification content withheld]"
            sensitive = True

        content_material = "\n".join(
            [
                str(signal.event_id),
                signal.package_name,
                signal.kind.value,
                signal.occurred_at.isoformat(),
                signal.sender_label or "",
                signal.conversation_label or "",
                text or "",
                signal.notification_key or "",
            ]
        )
        content_sha256 = hashlib.sha256(content_material.encode("utf-8")).hexdigest()

        return signal.model_copy(
            update={
                "source": expected_source,
                "text": text,
                "sensitive": sensitive,
                "content_sha256": content_sha256,
                "metadata": self._safe_metadata(signal.metadata),
            }
        )

    @staticmethod
    def _safe_metadata(
        metadata: dict[str, str | int | bool | float | None],
    ) -> dict[str, str | int | bool | float | None]:
        safe: dict[str, str | int | bool | float | None] = {}
        for key, value in metadata.items():
            normalized_key = key.strip().casefold()
            if not normalized_key or len(normalized_key) > 80:
                continue
            if any(
                token in normalized_key
                for token in ("token", "password", "cookie", "secret", "credential")
            ):
                continue
            if isinstance(value, str) and len(value) > 500:
                value = value[:500]
            safe[normalized_key] = value
        return safe

    @staticmethod
    def validate_action(kind: MobileActionKind, source: MobileSource) -> None:
        if kind is MobileActionKind.NOTIFICATION_REPLY and source in {
            MobileSource.PHONE,
            MobileSource.OTHER,
        }:
            raise MobilePolicyError("MOBILE_REPLY_SOURCE_UNSUPPORTED")
        if kind is MobileActionKind.DIAL_HANDOFF and source is not MobileSource.PHONE:
            raise MobilePolicyError("MOBILE_DIAL_SOURCE_INVALID")
        if kind is MobileActionKind.SMS_COMPOSE and source is not MobileSource.SMS:
            raise MobilePolicyError("MOBILE_SMS_SOURCE_INVALID")

    @staticmethod
    def capability_matrix() -> MobileCapabilityMatrix:
        return MobileCapabilityMatrix(
            device_trust_model=(
                "paired-device identity, HMAC request assertions, exact payload hash, "
                "short expiry, on-device biometric approval, and execution evidence"
            ),
            read_sources=(
                MobileSource.PHONE,
                MobileSource.SMS,
                MobileSource.WHATSAPP,
                MobileSource.INSTAGRAM,
                MobileSource.FACEBOOK_LITE,
            ),
            capabilities=(
                MobileCapabilityEntry(
                    capability_id="mobile.signals.ingest",
                    title="Ingest allowlisted phone communication signals",
                    status=MobileCapabilityStatus.ACTIVE,
                    approval_required=False,
                    limitation=(
                        "Notification access and user-shared content only unless the "
                        "companion is granted an Android default-handler role."
                    ),
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.signals.read",
                    title="Read normalized communication feed",
                    status=MobileCapabilityStatus.ACTIVE,
                    approval_required=False,
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.action.dial_handoff",
                    title="Open the phone dialer with an exact number",
                    status=MobileCapabilityStatus.CONDITIONAL,
                    approval_required=True,
                    limitation="The user still completes the call in the system dialer.",
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.action.sms_compose",
                    title="Open the SMS application with exact recipient and body",
                    status=MobileCapabilityStatus.CONDITIONAL,
                    approval_required=True,
                    limitation="Direct background SMS sending is disabled.",
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.action.notification_reply",
                    title="Reply through an app-provided notification action",
                    status=MobileCapabilityStatus.CONDITIONAL,
                    approval_required=True,
                    limitation=(
                        "Available only while the original notification exposes a valid "
                        "RemoteInput reply action."
                    ),
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.action.open_conversation",
                    title="Open an exact notification conversation",
                    status=MobileCapabilityStatus.CONDITIONAL,
                    approval_required=True,
                    limitation="Requires a valid app-provided PendingIntent.",
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.history.private_database",
                    title="Read private WhatsApp or Instagram application databases",
                    status=MobileCapabilityStatus.BLOCKED,
                    approval_required=False,
                    limitation="Android application sandbox and Nexuss policy prohibit it.",
                ),
                MobileCapabilityEntry(
                    capability_id="mobile.accessibility.autonomous_control",
                    title="Autonomous screen scraping and UI control",
                    status=MobileCapabilityStatus.BLOCKED,
                    approval_required=False,
                    limitation="Accessibility automation is not part of this milestone.",
                ),
            ),
        )

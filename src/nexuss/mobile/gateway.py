"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Process-local P4 phone pairing and session gateway.

This prototype intentionally supports private-LAN testing only. Native Android
certificate-backed enrollment is reserved for the production device-mesh phase.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.mobile.models import MobileDeviceSession, MobilePairingChallenge

_PAIRING_LIFETIME = timedelta(minutes=10)
_DEVICE_SESSION_LIFETIME = timedelta(hours=8)


class MobilePairingError(ValueError):
    """Raised when phone pairing or device authentication fails closed."""


@dataclass(frozen=True, slots=True)
class _PairingRecord:
    pairing_id: UUID
    code: str
    session_id: UUID
    mobile_url: str
    expires_at: datetime
    consumed: bool = False


@dataclass(frozen=True, slots=True)
class _DeviceRecord:
    device_id: UUID
    device_label: str
    session_id: UUID
    token_sha256: str
    expires_at: datetime


class MobileApprovalGateway:
    """Issue one-time pairing codes and authenticate paired phone sessions."""

    def __init__(self, *, mobile_url: str = "http://127.0.0.1:8100/mobile") -> None:
        self._mobile_url = mobile_url.rstrip("/")
        self._pairings: dict[str, _PairingRecord] = {}
        self._devices: dict[UUID, _DeviceRecord] = {}
        self._lock = RLock()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_pairing(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> MobilePairingChallenge:
        issued_at = now or datetime.now(UTC)
        with self._lock:
            expired_codes = [
                code for code, record in self._pairings.items() if record.expires_at <= issued_at
            ]
            for code in expired_codes:
                self._pairings.pop(code, None)
            for _attempt in range(20):
                code = f"{secrets.randbelow(100_000_000):08d}"
                if code not in self._pairings:
                    break
            else:
                raise MobilePairingError("PAIRING_CODE_GENERATION_FAILED")

            pairing_id = uuid5(
                NAMESPACE_URL,
                f"nexuss:mobile-pairing:{session_id}:{code}:{issued_at.isoformat()}",
            )
            record = _PairingRecord(
                pairing_id=pairing_id,
                code=code,
                session_id=session_id,
                mobile_url=self._mobile_url,
                expires_at=issued_at + _PAIRING_LIFETIME,
            )
            self._pairings[code] = record
            return MobilePairingChallenge(
                pairing_id=record.pairing_id,
                pairing_code=record.code,
                mobile_url=record.mobile_url,
                expires_at=record.expires_at,
            )

    def pair(
        self,
        pairing_code: str,
        device_label: str,
        *,
        now: datetime | None = None,
    ) -> MobileDeviceSession:
        paired_at = now or datetime.now(UTC)
        with self._lock:
            record = self._pairings.get(pairing_code)
            if record is None:
                raise MobilePairingError("PAIRING_CODE_INVALID")
            if record.consumed:
                raise MobilePairingError("PAIRING_CODE_ALREADY_USED")
            if paired_at >= record.expires_at:
                raise MobilePairingError("PAIRING_CODE_EXPIRED")

            token = secrets.token_urlsafe(48)
            device_id = uuid5(
                NAMESPACE_URL,
                f"nexuss:mobile-device:{record.session_id}:{device_label}:{token}",
            )
            device = _DeviceRecord(
                device_id=device_id,
                device_label=device_label.strip(),
                session_id=record.session_id,
                token_sha256=self._hash_token(token),
                expires_at=paired_at + _DEVICE_SESSION_LIFETIME,
            )
            self._devices[device_id] = device
            self._pairings[pairing_code] = _PairingRecord(
                pairing_id=record.pairing_id,
                code=record.code,
                session_id=record.session_id,
                mobile_url=record.mobile_url,
                expires_at=record.expires_at,
                consumed=True,
            )
            return MobileDeviceSession(
                device_id=device.device_id,
                device_label=device.device_label,
                device_token=token,
                expires_at=device.expires_at,
            )

    def authenticate(
        self,
        device_id: UUID,
        device_token: str,
        *,
        now: datetime | None = None,
    ) -> UUID:
        checked_at = now or datetime.now(UTC)
        with self._lock:
            record = self._devices.get(device_id)
            if record is None:
                raise MobilePairingError("MOBILE_DEVICE_NOT_PAIRED")
            if checked_at >= record.expires_at:
                self._devices.pop(device_id, None)
                raise MobilePairingError("MOBILE_DEVICE_SESSION_EXPIRED")
            if not secrets.compare_digest(record.token_sha256, self._hash_token(device_token)):
                raise MobilePairingError("MOBILE_DEVICE_TOKEN_INVALID")
            return record.session_id

    def revoke(self, device_id: UUID) -> None:
        with self._lock:
            self._devices.pop(device_id, None)

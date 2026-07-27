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

from nexuss.mobile.models import (
    MobileDeviceSession,
    MobileHandoffSummary,
    MobilePairedDevice,
    MobilePairingChallenge,
)
from nexuss.mobile.store import DeviceStore, InMemoryDeviceStore, StoredDevice

_PAIRING_LIFETIME = timedelta(minutes=10)

# A development trust anchor is re-authorised by use, not by the clock. The
# window is generous but bounded, and it slides forward while the phone stays
# in contact, so an abandoned device still ages out on its own.
_DEVICE_IDLE_LIFETIME = timedelta(days=30)

# Writing last_seen_at on every poll would mean roughly forty writes a minute
# per phone. Persist only once the recorded time is meaningfully stale.
_LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=1)


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
    paired_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class MobileApprovalGateway:
    """Issue one-time pairing codes and authenticate paired phone sessions."""

    def __init__(
        self,
        *,
        mobile_url: str = "http://127.0.0.1:8100/mobile",
        store: DeviceStore | None = None,
    ) -> None:
        self._mobile_url = mobile_url.rstrip("/")
        self._pairings: dict[str, _PairingRecord] = {}
        self._devices: dict[UUID, _DeviceRecord] = {}
        self._claimed_handoffs: dict[UUID, set[UUID]] = {}
        self._store: DeviceStore = store or InMemoryDeviceStore()
        self._lock = RLock()
        self._restore()

    def _restore(self) -> None:
        """Rehydrate paired devices after a Core restart.

        Handoff claims are deliberately not restored. A claim record only
        prevents replay within a running session; after a restart the
        freshness window in the core service is the guard that matters.
        """
        for stored in self._store.load_all():
            self._devices[stored.device_id] = _DeviceRecord(
                device_id=stored.device_id,
                device_label=stored.device_label,
                session_id=stored.session_id,
                token_sha256=stored.token_sha256,
                paired_at=stored.paired_at,
                last_seen_at=stored.last_seen_at,
                expires_at=stored.expires_at,
            )
            self._claimed_handoffs[stored.device_id] = set()

    def _persist(self, record: _DeviceRecord) -> None:
        self._store.upsert(
            StoredDevice(
                device_id=record.device_id,
                device_label=record.device_label,
                session_id=record.session_id,
                token_sha256=record.token_sha256,
                paired_at=record.paired_at,
                last_seen_at=record.last_seen_at,
                expires_at=record.expires_at,
            )
        )

    def list_devices(self) -> tuple[MobilePairedDevice, ...]:
        """Return every paired device, newest first. Digests are never exposed."""
        with self._lock:
            ordered = sorted(
                self._devices.values(),
                key=lambda record: record.paired_at,
                reverse=True,
            )
        return tuple(
            MobilePairedDevice(
                device_id=record.device_id,
                device_label=record.device_label,
                session_id=record.session_id,
                paired_at=record.paired_at,
                last_seen_at=record.last_seen_at,
                expires_at=record.expires_at,
            )
            for record in ordered
        )

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
            # Rotation. A displayed code is only as safe as the screen it is
            # on; issuing a new challenge must retire the previous one for
            # this session, or a photographed code stays live for ten minutes.
            superseded = [
                existing
                for existing, record in self._pairings.items()
                if record.session_id == session_id and not record.consumed
            ]
            for existing in superseded:
                self._pairings.pop(existing, None)

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
                paired_at=paired_at,
                last_seen_at=paired_at,
                expires_at=paired_at + _DEVICE_IDLE_LIFETIME,
            )
            self._devices[device_id] = device
            self._claimed_handoffs[device_id] = set()
            self._persist(device)
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
                self._claimed_handoffs.pop(device_id, None)
                self._store.delete(device_id)
                raise MobilePairingError("MOBILE_DEVICE_SESSION_EXPIRED")
            if not secrets.compare_digest(record.token_sha256, self._hash_token(device_token)):
                raise MobilePairingError("MOBILE_DEVICE_TOKEN_INVALID")

            # Contact renews the trust anchor. Persist sparingly: the phone
            # polls every 1.5s and this path is on the hot loop.
            renewed = _DeviceRecord(
                device_id=record.device_id,
                device_label=record.device_label,
                session_id=record.session_id,
                token_sha256=record.token_sha256,
                paired_at=record.paired_at,
                last_seen_at=checked_at,
                expires_at=checked_at + _DEVICE_IDLE_LIFETIME,
            )
            self._devices[record.device_id] = renewed
            if checked_at - record.last_seen_at >= _LAST_SEEN_WRITE_INTERVAL:
                self._persist(renewed)
            return record.session_id

    def claim_handoffs(
        self,
        device_id: UUID,
        handoffs: tuple[MobileHandoffSummary, ...],
    ) -> tuple[MobileHandoffSummary, ...]:
        with self._lock:
            if device_id not in self._devices:
                raise MobilePairingError("MOBILE_DEVICE_NOT_PAIRED")
            claimed = self._claimed_handoffs.setdefault(device_id, set())
            available = tuple(
                handoff
                for handoff in handoffs
                if handoff.task_id not in claimed
            )
            claimed.update(handoff.task_id for handoff in available)
            return available

    def rebind_sessions(self, session_id: UUID) -> tuple[int, int]:
        """Point every paired phone at the desktop session that is live now.

        The desktop identity lives in the browser and is regenerated whenever
        a fresh tab is opened. A phone paired against the previous identity
        stays authenticated but polls a session that no longer receives tasks,
        so approvals and handoffs return empty forever with no visible error.

        Returns (paired_devices, rebound_devices).
        """
        with self._lock:
            rebound = 0
            for device_id, record in list(self._devices.items()):
                if record.session_id == session_id:
                    continue
                rebound_record = _DeviceRecord(
                    device_id=record.device_id,
                    device_label=record.device_label,
                    session_id=session_id,
                    token_sha256=record.token_sha256,
                    paired_at=record.paired_at,
                    last_seen_at=record.last_seen_at,
                    expires_at=record.expires_at,
                )
                self._devices[device_id] = rebound_record
                self._persist(rebound_record)
                rebound += 1
            return len(self._devices), rebound

    def revoke(self, device_id: UUID) -> None:
        with self._lock:
            self._devices.pop(device_id, None)
            self._claimed_handoffs.pop(device_id, None)
            self._store.delete(device_id)

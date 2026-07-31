"""Device-bound request assertions for P6.7A mobile fabric endpoints."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

_ASSERTION_WINDOW = timedelta(minutes=2)


class MobileAssertionError(ValueError):
    """Raised when a mobile request assertion fails closed."""


@dataclass(frozen=True, slots=True)
class AssertionInput:
    method: str
    path: str
    timestamp: datetime
    nonce: str
    body_sha256: str

    def canonical(self) -> bytes:
        return "\n".join(
            [
                self.method.upper(),
                self.path,
                self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                self.nonce,
                self.body_sha256,
            ]
        ).encode("utf-8")


class DeviceAssertionVerifier:
    def __init__(self) -> None:
        self._seen: dict[str, datetime] = {}
        self._lock = RLock()

    @staticmethod
    def sign(device_token: str, assertion: AssertionInput) -> str:
        return hmac.new(
            device_token.encode("utf-8"),
            assertion.canonical(),
            hashlib.sha256,
        ).hexdigest()

    def verify(
        self,
        *,
        device_token: str,
        assertion: AssertionInput,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        observed_at = now or datetime.now(UTC)
        if assertion.timestamp.tzinfo is None:
            raise MobileAssertionError("MOBILE_ASSERTION_TIMESTAMP_REQUIRED")
        assertion_time = assertion.timestamp.astimezone(UTC)
        if abs(observed_at - assertion_time) > _ASSERTION_WINDOW:
            raise MobileAssertionError("MOBILE_ASSERTION_EXPIRED")
        if len(assertion.nonce) < 32:
            raise MobileAssertionError("MOBILE_ASSERTION_NONCE_INVALID")
        if len(assertion.body_sha256) != 64:
            raise MobileAssertionError("MOBILE_ASSERTION_BODY_HASH_INVALID")

        expected = self.sign(device_token, assertion)
        if not hmac.compare_digest(expected, signature.casefold()):
            raise MobileAssertionError("MOBILE_ASSERTION_SIGNATURE_INVALID")

        with self._lock:
            cutoff = observed_at - _ASSERTION_WINDOW
            stale = [nonce for nonce, used_at in self._seen.items() if used_at <= cutoff]
            for nonce in stale:
                self._seen.pop(nonce, None)
            if assertion.nonce in self._seen:
                raise MobileAssertionError("MOBILE_ASSERTION_REPLAYED")
            self._seen[assertion.nonce] = observed_at


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

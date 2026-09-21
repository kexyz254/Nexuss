"""Core-side client for the separately running local-control connector."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx

from nexuss.device.signing import sign_payload
from nexuss.local_control.models import (
    LocalControlCommandEnvelope,
    LocalControlOperation,
    LocalUpdateAccepted,
    LocalUpdateStatus,
)

_COMMAND_LIFETIME = timedelta(seconds=30)


class LocalControlError(RuntimeError):
    pass


class LocalControlClient(Protocol):
    def inspect_update(self) -> LocalUpdateStatus: ...

    def apply_update(
        self,
        *,
        expected_current_sha: str,
        expected_target_sha: str,
    ) -> LocalUpdateAccepted: ...


class DisabledLocalControlClient:
    def inspect_update(self) -> LocalUpdateStatus:
        raise LocalControlError("LOCAL_CONTROL_NOT_CONFIGURED")

    def apply_update(
        self,
        *,
        expected_current_sha: str,
        expected_target_sha: str,
    ) -> LocalUpdateAccepted:
        del expected_current_sha, expected_target_sha
        raise LocalControlError("LOCAL_CONTROL_NOT_CONFIGURED")


class HttpLocalControlClient:
    def __init__(
        self,
        *,
        base_url: str,
        shared_secret: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        if len(shared_secret) < 32:
            raise ValueError("Local-control secret must be at least 32 characters")

        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Local-control URL must be loopback HTTP")

        self._base_url = base_url.rstrip("/")
        self._shared_secret = shared_secret
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> LocalControlClient:
        base_url = os.getenv("NEXUSS_LOCAL_CONTROL_URL", "").strip()
        secret = os.getenv("NEXUSS_LOCAL_CONTROL_SECRET", "")
        if not base_url or not secret:
            return DisabledLocalControlClient()
        return cls(base_url=base_url, shared_secret=secret)

    def _post(
        self,
        envelope: LocalControlCommandEnvelope,
    ) -> dict[str, object]:
        signature = sign_payload(envelope, self._shared_secret)

        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self._base_url}/v1/update",
                    content=envelope.model_dump_json(),
                    headers={
                        "Content-Type": "application/json",
                        "X-Nexuss-Local-Signature": signature,
                    },
                )
        except httpx.HTTPError as exc:
            raise LocalControlError("LOCAL_CONTROL_UNREACHABLE") from exc

        if response.status_code != 200:
            raise LocalControlError(
                f"LOCAL_CONTROL_REJECTED_{response.status_code}"
            )

        payload = response.json()
        if not isinstance(payload, dict):
            raise LocalControlError("LOCAL_CONTROL_RESPONSE_INVALID")

        return {str(key): value for key, value in payload.items()}

    @staticmethod
    def _envelope(
        operation: LocalControlOperation,
        *,
        expected_current_sha: str | None = None,
        expected_target_sha: str | None = None,
    ) -> LocalControlCommandEnvelope:
        now = datetime.now(UTC)
        return LocalControlCommandEnvelope(
            command_id=uuid4(),
            operation=operation,
            expected_current_sha=expected_current_sha,
            expected_target_sha=expected_target_sha,
            issued_at=now,
            expires_at=now + _COMMAND_LIFETIME,
            nonce=secrets.token_urlsafe(32),
        )

    def inspect_update(self) -> LocalUpdateStatus:
        return LocalUpdateStatus.model_validate(
            self._post(
                self._envelope(LocalControlOperation.INSPECT_UPDATE)
            )
        )

    def apply_update(
        self,
        *,
        expected_current_sha: str,
        expected_target_sha: str,
    ) -> LocalUpdateAccepted:
        return LocalUpdateAccepted.model_validate(
            self._post(
                self._envelope(
                    LocalControlOperation.APPLY_UPDATE,
                    expected_current_sha=expected_current_sha,
                    expected_target_sha=expected_target_sha,
                )
            )
        )

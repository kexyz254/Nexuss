"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Core-side client for a separately running trusted Windows device node.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from nexuss.device.models import (
    DeviceCommandEnvelope,
    DeviceCommandEvidence,
    DeviceRollbackEnvelope,
    DeviceRollbackEvidence,
)
from nexuss.device.signing import sign_payload

_DEVICE_COMMAND_LIFETIME = timedelta(seconds=30)


class DeviceCommandError(RuntimeError):
    """Raised when the trusted device node rejects or cannot verify a command."""


class DeviceNodeClient(Protocol):
    def launch_notepad(
        self,
        task_id: UUID,
        target_node_id: str,
    ) -> DeviceCommandEvidence: ...

    def open_web_search(
        self,
        task_id: UUID,
        target_node_id: str,
        launch_url: str,
    ) -> DeviceCommandEvidence: ...

    def rollback_command(
        self,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceRollbackEvidence: ...


class DisabledDeviceNodeClient:
    """Fail-closed client used when the device node is not configured."""

    def launch_notepad(
        self,
        task_id: UUID,
        target_node_id: str,
    ) -> DeviceCommandEvidence:
        del task_id, target_node_id
        raise DeviceCommandError("TRUSTED_DEVICE_NODE_NOT_CONFIGURED")

    def open_web_search(
        self,
        task_id: UUID,
        target_node_id: str,
        launch_url: str,
    ) -> DeviceCommandEvidence:
        del task_id, target_node_id, launch_url
        raise DeviceCommandError("TRUSTED_DEVICE_NODE_NOT_CONFIGURED")

    def rollback_command(
        self,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceRollbackEvidence:
        del task_id, command_id, target_node_id
        raise DeviceCommandError("TRUSTED_DEVICE_NODE_NOT_CONFIGURED")


class HttpDeviceNodeClient:
    """Send short-lived signed envelopes to the loopback-only Windows node."""

    def __init__(
        self,
        *,
        base_url: str,
        shared_secret: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        if len(shared_secret) < 32:
            raise ValueError(
                "Device-node shared secret must contain at least 32 characters"
            )
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "Device-node URL must be an unauthenticated loopback HTTP endpoint"
            )
        self._base_url = base_url.rstrip("/")
        self._shared_secret = shared_secret
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> DeviceNodeClient:
        base_url = os.getenv("NEXUSS_DEVICE_NODE_URL", "").strip()
        shared_secret = os.getenv("NEXUSS_DEVICE_NODE_SECRET", "")
        if not base_url or not shared_secret:
            return DisabledDeviceNodeClient()
        return cls(base_url=base_url, shared_secret=shared_secret)

    def _post(
        self,
        path: str,
        envelope: DeviceCommandEnvelope | DeviceRollbackEnvelope,
    ) -> dict[str, object]:
        signature = sign_payload(envelope, self._shared_secret)
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self._base_url}{path}",
                    content=envelope.model_dump_json(),
                    headers={
                        "Content-Type": "application/json",
                        "X-Nexuss-Node-Signature": signature,
                    },
                )
        except httpx.HTTPError as exc:
            raise DeviceCommandError("TRUSTED_DEVICE_NODE_UNREACHABLE") from exc
        if response.status_code != 200:
            raise DeviceCommandError(
                f"TRUSTED_DEVICE_NODE_REJECTED_{response.status_code}"
            )
        payload: object = response.json()
        if not isinstance(payload, dict):
            raise DeviceCommandError("TRUSTED_DEVICE_NODE_RESPONSE_INVALID")
        return {str(key): value for key, value in payload.items()}

    def launch_notepad(
        self,
        task_id: UUID,
        target_node_id: str,
    ) -> DeviceCommandEvidence:
        now = datetime.now(UTC)
        command_id = uuid5(
            NAMESPACE_URL,
            (
                "nexuss:device-command:"
                f"{task_id}:device.launch_notepad:{target_node_id}"
            ),
        )
        envelope = DeviceCommandEnvelope(
            command_id=command_id,
            task_id=task_id,
            capability_id="device.launch_notepad",
            target_node_id=target_node_id,
            issued_at=now,
            expires_at=now + _DEVICE_COMMAND_LIFETIME,
            nonce=secrets.token_urlsafe(32),
            parameters={},
        )
        return DeviceCommandEvidence.model_validate(
            self._post("/v1/commands", envelope)
        )

    def open_web_search(
        self,
        task_id: UUID,
        target_node_id: str,
        launch_url: str,
    ) -> DeviceCommandEvidence:
        now = datetime.now(UTC)
        command_id = uuid5(
            NAMESPACE_URL,
            (
                "nexuss:device-command:"
                f"{task_id}:device.open_web_search:{target_node_id}:{launch_url}"
            ),
        )
        envelope = DeviceCommandEnvelope(
            command_id=command_id,
            task_id=task_id,
            capability_id="device.open_web_search",
            target_node_id=target_node_id,
            issued_at=now,
            expires_at=now + _DEVICE_COMMAND_LIFETIME,
            nonce=secrets.token_urlsafe(32),
            parameters={"launch_url": launch_url},
        )
        return DeviceCommandEvidence.model_validate(
            self._post("/v1/commands", envelope)
        )

    def rollback_command(
        self,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceRollbackEvidence:
        now = datetime.now(UTC)
        envelope = DeviceRollbackEnvelope(
            rollback_id=uuid5(
                NAMESPACE_URL,
                f"nexuss:device-rollback:{task_id}:{command_id}",
            ),
            task_id=task_id,
            command_id=command_id,
            target_node_id=target_node_id,
            issued_at=now,
            expires_at=now + _DEVICE_COMMAND_LIFETIME,
            nonce=secrets.token_urlsafe(32),
        )
        return DeviceRollbackEvidence.model_validate(
            self._post("/v1/rollbacks", envelope)
        )

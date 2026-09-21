"""Loopback-only FastAPI service for Nexuss local self-management."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import RLock
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status

from nexuss.device.signing import DeviceSignatureError, verify_signature
from nexuss.local_control.models import (
    LocalControlCommandEnvelope,
    LocalControlHealth,
    LocalControlOperation,
    LocalUpdateAccepted,
    LocalUpdateStatus,
)
from nexuss.local_control.repository import (
    GitRepositoryManager,
    LocalRepositoryError,
)

app = FastAPI(title="Nexuss Local Control Connector", version="0.6.16b")
repository = GitRepositoryManager()
_seen_nonces: dict[str, datetime] = {}
_nonce_lock = RLock()


def _shared_secret() -> str:
    secret = os.getenv("NEXUSS_LOCAL_CONTROL_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOCAL_CONTROL_SECRET_NOT_CONFIGURED",
        )
    return secret


def _authorize(
    envelope: LocalControlCommandEnvelope,
    signature: str,
) -> None:
    now = datetime.now(UTC)
    if envelope.issued_at > now or now >= envelope.expires_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LOCAL_CONTROL_ENVELOPE_EXPIRED",
        )

    try:
        verify_signature(envelope, _shared_secret(), signature)
    except DeviceSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LOCAL_CONTROL_SIGNATURE_INVALID",
        ) from exc

    with _nonce_lock:
        for nonce, expires_at in tuple(_seen_nonces.items()):
            if expires_at <= now:
                _seen_nonces.pop(nonce, None)

        if envelope.nonce in _seen_nonces:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="LOCAL_CONTROL_NONCE_REPLAYED",
            )

        _seen_nonces[envelope.nonce] = envelope.expires_at


@app.get("/health/ready", response_model=LocalControlHealth)
def health_ready() -> LocalControlHealth:
    return LocalControlHealth(
        status="ready",
        mode="p616b_trusted_local_control",
        repository_root=str(repository.root),
        approved_branch=repository.approved_branch,
    )


@app.post("/v1/update", response_model=LocalUpdateStatus | LocalUpdateAccepted)
def update_command(
    envelope: LocalControlCommandEnvelope,
    signature: Annotated[
        str,
        Header(alias="X-Nexuss-Local-Signature"),
    ],
) -> LocalUpdateStatus | LocalUpdateAccepted:
    _authorize(envelope, signature)

    try:
        if envelope.operation is LocalControlOperation.INSPECT_UPDATE:
            return repository.inspect(branch=envelope.branch)

        if (
            envelope.expected_current_sha is None
            or envelope.expected_target_sha is None
        ):
            raise LocalRepositoryError(
                "LOCAL_UPDATE_APPROVAL_SHA_MISSING",
                "Approved current and target SHAs are required.",
            )

        return repository.apply_fast_forward(
            expected_current_sha=envelope.expected_current_sha,
            expected_target_sha=envelope.expected_target_sha,
            branch=envelope.branch,
        )
    except LocalRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

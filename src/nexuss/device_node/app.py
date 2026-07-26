"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Loopback-only FastAPI service for the P4 trusted Windows device node.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import RLock
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status

from nexuss.device.models import (
    DeviceCommandEnvelope,
    DeviceCommandEvidence,
    DeviceRollbackEnvelope,
    DeviceRollbackEvidence,
)
from nexuss.device.signing import DeviceSignatureError, verify_signature
from nexuss.device_node.executor import NodeExecutionError, WindowsNotepadExecutor

app = FastAPI(title="Nexuss Windows Device Node", version="0.4.0")
executor = WindowsNotepadExecutor()
_seen_nonces: dict[str, datetime] = {}
_nonce_lock = RLock()


def reset_nonce_cache() -> None:
    """Clear replay state for an isolated process-level test or controlled restart."""
    with _nonce_lock:
        _seen_nonces.clear()


def _shared_secret() -> str:
    secret = os.getenv("NEXUSS_DEVICE_NODE_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEVICE_NODE_SECRET_NOT_CONFIGURED",
        )
    return secret


def _authorize(envelope: DeviceCommandEnvelope | DeviceRollbackEnvelope, signature: str) -> None:
    now = datetime.now(UTC)
    if envelope.issued_at > now or now >= envelope.expires_at:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DEVICE_ENVELOPE_EXPIRED")
    try:
        verify_signature(envelope, _shared_secret(), signature)
    except DeviceSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    with _nonce_lock:
        expired_nonces = [
            nonce for nonce, expires_at in _seen_nonces.items() if expires_at <= now
        ]
        for nonce in expired_nonces:
            _seen_nonces.pop(nonce, None)
        if envelope.nonce in _seen_nonces:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="DEVICE_NONCE_REPLAYED",
            )
        _seen_nonces[envelope.nonce] = envelope.expires_at


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {
        "status": "ready",
        "mode": "p4_trusted_windows_node",
        "node_id": executor.node_id,
    }


@app.post("/v1/commands", response_model=DeviceCommandEvidence)
def execute_command(
    envelope: DeviceCommandEnvelope,
    signature: Annotated[str, Header(alias="X-Nexuss-Node-Signature")],
) -> DeviceCommandEvidence:
    _authorize(envelope, signature)
    if envelope.capability_id != "device.launch_notepad":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CAPABILITY_NOT_ALLOWLISTED",
        )
    try:
        return executor.launch(
            task_id=envelope.task_id,
            command_id=envelope.command_id,
            target_node_id=envelope.target_node_id,
        )
    except NodeExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/v1/rollbacks", response_model=DeviceRollbackEvidence)
def rollback_command(
    envelope: DeviceRollbackEnvelope,
    signature: Annotated[str, Header(alias="X-Nexuss-Node-Signature")],
) -> DeviceRollbackEvidence:
    _authorize(envelope, signature)
    try:
        return executor.rollback(
            rollback_id=envelope.rollback_id,
            task_id=envelope.task_id,
            command_id=envelope.command_id,
            target_node_id=envelope.target_node_id,
        )
    except NodeExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

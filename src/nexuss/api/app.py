"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

FastAPI surface for the Nexuss P4 trusted-device mesh and phone approval client.
"""

from __future__ import annotations

import ipaddress
import os
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nexuss.core.registry import list_capabilities
from nexuss.core.service import (
    ApprovalValidationError,
    CoreSimulatorService,
    InvalidSessionError,
    RollbackValidationError,
    TaskNotFoundError,
)
from nexuss.device.client import HttpDeviceNodeClient
from nexuss.domain.models import (
    ActionReceipt,
    ApprovalChannel,
    ApprovalDecision,
    AssuranceLevel,
    CapabilityManifest,
    IdentitySession,
    RollbackRequest,
    TaskRequest,
    TaskView,
)
from nexuss.mobile.gateway import MobileApprovalGateway, MobilePairingError
from nexuss.mobile.models import (
    MobileApprovalSummary,
    MobileDecisionRequest,
    MobileDeviceSession,
    MobilePairingChallenge,
    MobilePairRequest,
)

_UI_DIRECTORY = Path(__file__).resolve().parents[1] / "ui"
_MOBILE_URL = os.getenv("NEXUSS_MOBILE_PUBLIC_URL", "http://127.0.0.1:8100/mobile")

app = FastAPI(
    title="Nexuss Core API",
    version="0.4.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=_UI_DIRECTORY), name="nexuss-ui-assets")
service = CoreSimulatorService(device_client=HttpDeviceNodeClient.from_environment())
mobile_gateway = MobileApprovalGateway(mobile_url=_MOBILE_URL)
_PAIR_ATTEMPT_WINDOW = timedelta(minutes=5)
_PAIR_ATTEMPT_LIMIT = 5
_pair_attempts: dict[str, deque[datetime]] = defaultdict(deque)
_pair_attempt_lock = RLock()


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else ""


def _require_local_control(request: Request) -> None:
    host = _client_host(request)
    if host == "testclient":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="LOCAL_CONTROL_ENDPOINT_REQUIRED",
    )


def _enforce_pair_rate_limit(request: Request) -> None:
    host = _client_host(request) or "unknown"
    now = datetime.now(UTC)
    cutoff = now - _PAIR_ATTEMPT_WINDOW
    with _pair_attempt_lock:
        attempts = _pair_attempts[host]
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= _PAIR_ATTEMPT_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="MOBILE_PAIRING_RATE_LIMITED",
            )
        attempts.append(now)


def _session(
    session_id: UUID,
    authenticated: bool,
    assurance_level: AssuranceLevel = AssuranceLevel.BASIC,
) -> IdentitySession:
    return IdentitySession(
        session_id=session_id,
        authenticated=authenticated,
        assurance_level=assurance_level,
    )


def _mobile_identity(device_id: UUID, device_token: str) -> IdentitySession:
    try:
        session_id = mobile_gateway.authenticate(device_id, device_token)
    except MobilePairingError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _session(session_id, True, AssuranceLevel.STRONG)


@app.get("/", include_in_schema=False)
def ui_index(request: Request) -> FileResponse:
    _require_local_control(request)
    return FileResponse(
        _UI_DIRECTORY / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/mobile", include_in_schema=False)
def mobile_index() -> FileResponse:
    return FileResponse(
        _UI_DIRECTORY / "mobile.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {
        "status": "alive",
        "service": "nexuss-core-api",
        "version": "0.4.0",
    }


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {
        "status": "ready",
        "mode": "p4_trusted_device_mesh",
        "phone_approval": "enabled",
    }


@app.get("/v1/capabilities", response_model=list[CapabilityManifest])
def get_capabilities(request: Request) -> list[CapabilityManifest]:
    _require_local_control(request)
    return list(list_capabilities())


@app.post("/v1/tasks", response_model=TaskView, status_code=status.HTTP_202_ACCEPTED)
def create_task(
    request: TaskRequest,
    http_request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    _require_local_control(http_request)
    try:
        return service.create_task(request, _session(session_id, session_authenticated))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@app.post("/v1/tasks/{task_id}/approval", response_model=TaskView)
def decide_task_approval(
    task_id: UUID,
    decision: ApprovalDecision,
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    _require_local_control(request)
    try:
        return service.approve_task(
            task_id,
            decision,
            _session(session_id, session_authenticated),
            approval_channel=ApprovalChannel.DESKTOP,
        )
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except ApprovalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/v1/tasks/{task_id}/rollback", response_model=TaskView)
def rollback_task(
    task_id: UUID,
    rollback_request: RollbackRequest,
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    del rollback_request
    _require_local_control(request)
    try:
        return service.rollback_task(task_id, _session(session_id, session_authenticated))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except RollbackValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/v1/tasks/{task_id}", response_model=TaskView)
def get_task(task_id: UUID, request: Request) -> TaskView:
    _require_local_control(request)
    try:
        return service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc


@app.get("/v1/tasks/{task_id}/receipt", response_model=ActionReceipt)
def get_task_receipt(task_id: UUID, request: Request) -> ActionReceipt:
    _require_local_control(request)
    try:
        return service.get_receipt(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        ) from exc


@app.get("/v1/tasks/{task_id}/receipts", response_model=list[ActionReceipt])
def get_task_receipt_history(task_id: UUID, request: Request) -> list[ActionReceipt]:
    _require_local_control(request)
    try:
        return list(service.get_receipt_history(task_id))
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt history not found",
        ) from exc


@app.post("/v1/mobile/pairing", response_model=MobilePairingChallenge)
def create_mobile_pairing(
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> MobilePairingChallenge:
    _require_local_control(request)
    if not session_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_NOT_AUTHENTICATED",
        )
    try:
        return mobile_gateway.create_pairing(session_id)
    except MobilePairingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/v1/mobile/pair", response_model=MobileDeviceSession)
def pair_mobile_device(
    pair_request: MobilePairRequest,
    request: Request,
) -> MobileDeviceSession:
    _enforce_pair_rate_limit(request)
    try:
        return mobile_gateway.pair(pair_request.pairing_code, pair_request.device_label)
    except MobilePairingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/v1/mobile/pending", response_model=list[MobileApprovalSummary])
def get_mobile_pending_approvals(
    device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
    device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
) -> list[MobileApprovalSummary]:
    identity = _mobile_identity(device_id, device_token)
    return list(service.list_pending_phone_approvals(identity.session_id))


@app.post("/v1/mobile/tasks/{task_id}/decision", response_model=TaskView)
def decide_mobile_approval(
    task_id: UUID,
    request: MobileDecisionRequest,
    device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
    device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
) -> TaskView:
    identity = _mobile_identity(device_id, device_token)
    decision = ApprovalDecision(
        approval_id=request.approval_id,
        approval_token=request.approval_token,
        payload_sha256=request.payload_sha256,
        decision=request.decision,
    )
    try:
        return service.approve_task(
            task_id,
            decision,
            identity,
            approval_channel=ApprovalChannel.PHONE,
        )
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except (InvalidSessionError, ApprovalValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

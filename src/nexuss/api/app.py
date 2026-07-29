"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

FastAPI surface for the Nexuss P5 knowledge, media, and mobile action plane.
"""

from __future__ import annotations

import ipaddress
import os
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from nexuss.archive.workflow import (
    ArchiveApprovalValidationError,
    ArchiveImportCoordinator,
    ArchiveSessionError,
    ArchiveTaskNotFoundError,
    ArchiveWorkflowError,
)
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
from nexuss.memory.store import memory_store_from_environment
from nexuss.mobile.gateway import MobileApprovalGateway, MobilePairingError
from nexuss.mobile.models import (
    MobileApprovalSummary,
    MobileDecisionRequest,
    MobileDeviceSession,
    MobileHandoffSummary,
    MobilePairedDevice,
    MobilePairingChallenge,
    MobilePairRequest,
    MobileRebindResult,
)
from nexuss.mobile.store import device_store_from_environment

_UI_DIRECTORY = Path(__file__).resolve().parents[1] / "ui"
_MOBILE_URL = os.getenv("NEXUSS_MOBILE_PUBLIC_URL", "http://127.0.0.1:8100/mobile")

app = FastAPI(
    title="Nexuss Core API",
    version="0.5.2",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=_UI_DIRECTORY), name="nexuss-ui-assets")
mobile_gateway = MobileApprovalGateway(
    mobile_url=_MOBILE_URL,
    store=device_store_from_environment(),
)
service = CoreSimulatorService(
    device_client=HttpDeviceNodeClient.from_environment(),
    pairing_gateway=mobile_gateway,
    memory_store=memory_store_from_environment(),
)
archive_imports = ArchiveImportCoordinator.from_environment()
_PAIR_ATTEMPT_WINDOW = timedelta(minutes=5)
_PAIR_ATTEMPT_LIMIT = 5
_pair_attempts: dict[str, deque[datetime]] = defaultdict(deque)
_pair_attempt_lock = RLock()

_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://www.youtube.com https://s.ytimg.com; "
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
    "img-src 'self' data: https://i.ytimg.com https://yt3.ggpht.com; "
    "style-src 'self'; connect-src 'self'; media-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def add_security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _SECURITY_POLICY
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=()"
    return response


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
        "version": "0.5.2",
    }


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {
        "status": "ready",
        "mode": "p65f_native_zip_github_import",
        "phone_approval": "enabled",
    }


@app.get("/v1/capabilities", response_model=list[CapabilityManifest])
def get_capabilities(request: Request) -> list[CapabilityManifest]:
    _require_local_control(request)
    return list(list_capabilities())


@app.post(
    "/v1/archive-imports",
    response_model=TaskView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_archive_import(
    request: Request,
    request_id: Annotated[UUID, Header(alias="X-Nexuss-Request-ID")],
    repository_name: Annotated[
        str,
        Header(alias="X-Nexuss-Repository-Name"),
    ],
    archive_name: Annotated[
        str,
        Header(alias="X-Nexuss-Archive-Name"),
    ],
    session_id: Annotated[
        UUID,
        Header(alias="X-Nexuss-Session-ID"),
    ],
    session_authenticated: Annotated[
        bool,
        Header(alias="X-Nexuss-Session-Authenticated"),
    ],
    content_length: Annotated[
        int | None,
        Header(alias="Content-Length"),
    ] = None,
) -> TaskView:
    """Quarantine one ZIP and prepare two phone-approved GitHub writes."""

    _require_local_control(request)
    identity = _session(session_id, session_authenticated)
    try:
        return await archive_imports.create_task_from_stream(
            request.stream(),
            request_id=request_id,
            session=identity,
            repository_name=repository_name,
            archive_name=archive_name,
            content_type=request.headers.get(
                "content-type",
                "application/octet-stream",
            ),
            content_length=content_length,
        )
    except ArchiveSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except ArchiveWorkflowError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "safe_details": exc.safe_details,
            },
        ) from exc


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
    identity = _session(session_id, session_authenticated)
    try:
        if archive_imports.contains_task(task_id):
            return archive_imports.approve_task(
                task_id,
                decision,
                identity,
                approval_channel=ApprovalChannel.DESKTOP,
            )
        return service.approve_task(
            task_id,
            decision,
            identity,
            approval_channel=ApprovalChannel.DESKTOP,
        )
    except (InvalidSessionError, ArchiveSessionError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except (TaskNotFoundError, ArchiveTaskNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except (ApprovalValidationError, ArchiveApprovalValidationError) as exc:
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
        if archive_imports.contains_task(task_id):
            return archive_imports.get_task(task_id)
        return service.get_task(task_id)
    except (TaskNotFoundError, ArchiveTaskNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc


@app.get("/v1/tasks/{task_id}/receipt", response_model=ActionReceipt)
def get_task_receipt(task_id: UUID, request: Request) -> ActionReceipt:
    _require_local_control(request)
    try:
        if archive_imports.contains_task(task_id):
            return archive_imports.get_receipt(task_id)
        return service.get_receipt(task_id)
    except (TaskNotFoundError, ArchiveTaskNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        ) from exc


@app.get("/v1/tasks/{task_id}/receipts", response_model=list[ActionReceipt])
def get_task_receipt_history(task_id: UUID, request: Request) -> list[ActionReceipt]:
    _require_local_control(request)
    try:
        if archive_imports.contains_task(task_id):
            return list(archive_imports.get_receipt_history(task_id))
        return list(service.get_receipt_history(task_id))
    except (TaskNotFoundError, ArchiveTaskNotFoundError) as exc:
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


@app.get("/v1/mobile/devices", response_model=list[MobilePairedDevice])
def list_mobile_devices(
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> list[MobilePairedDevice]:
    """List paired phones. Token digests are never exposed."""
    del session_id
    _require_local_control(request)
    if not session_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_NOT_AUTHENTICATED",
        )
    return list(mobile_gateway.list_devices())


@app.delete("/v1/mobile/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_mobile_device(
    device_id: UUID,
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> None:
    """Unpair a phone immediately and irreversibly."""
    del session_id
    _require_local_control(request)
    if not session_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_NOT_AUTHENTICATED",
        )
    mobile_gateway.revoke(device_id)


@app.post("/v1/mobile/devices/rebind", response_model=MobileRebindResult)
def rebind_mobile_devices(
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> MobileRebindResult:
    """Rebind already-paired phones to the caller's desktop session.

    Loopback-only and authenticated, so this grants nothing that creating a
    task from the same origin does not already grant.
    """
    _require_local_control(request)
    if not session_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_NOT_AUTHENTICATED",
        )
    paired, rebound = mobile_gateway.rebind_sessions(session_id)
    return MobileRebindResult(
        session_id=session_id,
        paired_devices=paired,
        rebound_devices=rebound,
    )


@app.get("/v1/mobile/pending", response_model=list[MobileApprovalSummary])
def get_mobile_pending_approvals(
    device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
    device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
) -> list[MobileApprovalSummary]:
    identity = _mobile_identity(device_id, device_token)
    pending = [
        *service.list_pending_phone_approvals(identity.session_id),
        *archive_imports.list_pending_phone_approvals(identity.session_id),
    ]
    return sorted(pending, key=lambda item: item.expires_at)


@app.get("/v1/mobile/handoffs", response_model=list[MobileHandoffSummary])
def get_mobile_handoffs(
    device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
    device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
) -> list[MobileHandoffSummary]:
    identity = _mobile_identity(device_id, device_token)
    handoffs = service.list_phone_handoffs(identity.session_id)
    try:
        return list(mobile_gateway.claim_handoffs(device_id, handoffs))
    except MobilePairingError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


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
        if archive_imports.contains_task(task_id):
            return archive_imports.approve_task(
                task_id,
                decision,
                identity,
                approval_channel=ApprovalChannel.PHONE,
            )
        return service.approve_task(
            task_id,
            decision,
            identity,
            approval_channel=ApprovalChannel.PHONE,
        )
    except (TaskNotFoundError, ArchiveTaskNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        ) from exc
    except (
        InvalidSessionError,
        ApprovalValidationError,
        ArchiveSessionError,
        ArchiveApprovalValidationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

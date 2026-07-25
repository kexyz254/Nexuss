"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

FastAPI surface for the Nexuss P3 approved-action platform and premium UI.
"""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, status
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
from nexuss.domain.models import (
    ActionReceipt,
    ApprovalDecision,
    AssuranceLevel,
    CapabilityManifest,
    IdentitySession,
    RollbackRequest,
    TaskRequest,
    TaskView,
)

_UI_DIRECTORY = Path(__file__).resolve().parents[1] / "ui"

app = FastAPI(title="Nexuss Core API", version="0.3.0")
app.mount("/assets", StaticFiles(directory=_UI_DIRECTORY), name="nexuss-ui-assets")
service = CoreSimulatorService()


def _session(session_id: UUID, authenticated: bool) -> IdentitySession:
    return IdentitySession(
        session_id=session_id,
        authenticated=authenticated,
        assurance_level=AssuranceLevel.BASIC,
    )


@app.get("/", include_in_schema=False)
def ui_index() -> FileResponse:
    return FileResponse(
        _UI_DIRECTORY / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {
        "status": "alive",
        "service": "nexuss-core-api",
        "version": "0.3.0",
    }


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ready", "mode": "p3_approved_actions"}


@app.get("/v1/capabilities", response_model=list[CapabilityManifest])
def get_capabilities() -> list[CapabilityManifest]:
    return list(list_capabilities())


@app.post("/v1/tasks", response_model=TaskView, status_code=status.HTTP_202_ACCEPTED)
def create_task(
    request: TaskRequest,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    try:
        return service.create_task(request, _session(session_id, session_authenticated))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@app.post("/v1/tasks/{task_id}/approval", response_model=TaskView)
def decide_task_approval(
    task_id: UUID,
    decision: ApprovalDecision,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    try:
        return service.approve_task(
            task_id,
            decision,
            _session(session_id, session_authenticated),
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
    request: RollbackRequest,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    del request
    try:
        return service.rollback_task(task_id, _session(session_id, session_authenticated))
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except RollbackValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/v1/tasks/{task_id}", response_model=TaskView)
def get_task(task_id: UUID) -> TaskView:
    try:
        return service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc


@app.get("/v1/tasks/{task_id}/receipt", response_model=ActionReceipt)
def get_task_receipt(task_id: UUID) -> ActionReceipt:
    try:
        return service.get_receipt(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        ) from exc


@app.get("/v1/tasks/{task_id}/receipts", response_model=list[ActionReceipt])
def get_task_receipt_history(task_id: UUID) -> list[ActionReceipt]:
    try:
        return list(service.get_receipt_history(task_id))
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt history not found",
        ) from exc

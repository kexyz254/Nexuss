"""FastAPI surface for the Nexuss P1 Core Simulator."""

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, status

from nexuss.core.service import CoreSimulatorService, InvalidSessionError, TaskNotFoundError
from nexuss.domain.models import (
    ActionReceipt,
    AssuranceLevel,
    IdentitySession,
    TaskRequest,
    TaskView,
)

app = FastAPI(title="Nexuss Core API", version="0.1.0")
service = CoreSimulatorService()


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    return {"status": "ready", "mode": "p1_simulator"}


@app.post("/v1/tasks", response_model=TaskView, status_code=status.HTTP_202_ACCEPTED)
def create_task(
    request: TaskRequest,
    session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
    session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
) -> TaskView:
    session = IdentitySession(
        session_id=session_id,
        authenticated=session_authenticated,
        assurance_level=AssuranceLevel.BASIC,
    )
    try:
        return service.create_task(request, session)
    except InvalidSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


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

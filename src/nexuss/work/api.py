"""Authenticated APIs for persistent Nexuss work."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status

from nexuss.work.models import (
    CreateProjectRequest,
    CreateWorkItemRequest,
    ProjectRecord,
    UpdateWorkItemRequest,
    WorkItemRecord,
    WorkOverview,
)
from nexuss.work.store import SQLiteWorkStore, WorkStoreError


def register_work_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> SQLiteWorkStore:
    store = SQLiteWorkStore()

    def require_session(authenticated: bool) -> None:
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session is required.",
            )

    @app.get("/v1/work/overview", response_model=WorkOverview)
    def overview(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> WorkOverview:
        require_local_control(request)
        require_session(authenticated)
        return WorkOverview(
            projects=store.list_projects(session_id),
            items=store.list_items(session_id),
        )

    @app.post("/v1/work/projects", response_model=ProjectRecord, status_code=201)
    def create_project(
        body: CreateProjectRequest,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> ProjectRecord:
        require_local_control(request)
        require_session(authenticated)
        try:
            return store.create_project(
                user_session_id=session_id,
                title=body.title,
                description=body.description,
            )
        except WorkStoreError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/v1/work/items", response_model=WorkItemRecord, status_code=201)
    def create_item(
        body: CreateWorkItemRequest,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> WorkItemRecord:
        require_local_control(request)
        require_session(authenticated)
        try:
            return store.create_item(
                user_session_id=session_id,
                title=body.title,
                conversation_id=body.conversation_id,
                project_id=body.project_id,
                description=body.description,
                priority=body.priority,
                due_at=body.due_at,
                dependency_ids=body.dependency_ids,
                resume_context=body.resume_context,
            )
        except WorkStoreError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.patch("/v1/work/items/{work_item_id}", response_model=WorkItemRecord)
    def update_item(
        work_item_id: UUID,
        body: UpdateWorkItemRequest,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> WorkItemRecord:
        require_local_control(request)
        require_session(authenticated)
        try:
            return store.update_status(
                user_session_id=session_id,
                work_item_id=work_item_id,
                status=body.status,
            )
        except WorkStoreError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc

    return store

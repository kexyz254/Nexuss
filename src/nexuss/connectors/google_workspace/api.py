"""Loopback-only Google Workspace read API."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, status

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.google_workspace.models import (
    GoogleWorkspaceHealth,
    GoogleWorkspaceSnapshot,
)
from nexuss.connectors.google_workspace.service import GoogleWorkspaceConnectorService


def register_google_workspace_routes(
    app: FastAPI,
    require_local_control: Callable[[Request], None],
    *,
    service: GoogleWorkspaceConnectorService,
) -> None:
    def authorize(request: Request, *, authenticated: bool) -> None:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_NOT_AUTHENTICATED",
            )

    @app.get(
        "/v1/google-workspace/health",
        response_model=GoogleWorkspaceHealth,
    )
    def google_workspace_health(request: Request) -> GoogleWorkspaceHealth:
        require_local_control(request)
        return service.health()

    @app.get(
        "/v1/google-workspace/snapshot",
        response_model=GoogleWorkspaceSnapshot,
    )
    def google_workspace_snapshot(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[
            bool, Header(alias="X-Nexuss-Session-Authenticated")
        ],
        days_back: Annotated[int, Query(ge=1, le=30)] = 14,
        days_forward: Annotated[int, Query(ge=1, le=30)] = 14,
    ) -> GoogleWorkspaceSnapshot:
        del session_id
        authorize(request, authenticated=authenticated)
        now = datetime.now(UTC)
        try:
            return service.snapshot(
                time_min=now - timedelta(days=days_back),
                time_max=now + timedelta(days=days_forward),
                gmail_query=f"newer_than:{days_back}d",
            )
        except ConnectorError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": exc.code,
                    "message": exc.message,
                    "safe_details": exc.safe_details,
                },
            ) from exc

"""Local control API for the Nexuss Agent Supervisor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request, status

from nexuss.orchestration.supervisor import (
    AgentSupervisorError,
    AgentSupervisorService,
)
from nexuss.orchestration.supervisor_models import (
    RegisterSupervisorAgentRequest,
    SupervisorAgent,
    SupervisorEvent,
    SupervisorHeartbeatRequest,
    SupervisorSnapshot,
)
from nexuss.orchestration.supervisor_store import SQLiteSupervisorStore


def register_supervisor_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
    core_service: object,
) -> AgentSupervisorService:
    service = AgentSupervisorService(
        core_service=core_service,
        store=SQLiteSupervisorStore(),
    )

    def require_authenticated(authenticated: bool) -> None:
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated desktop session is required.",
            )

    @app.get(
        "/v1/supervisor/snapshot",
        response_model=SupervisorSnapshot,
    )
    def get_supervisor_snapshot(
        request: Request,
        event_limit: int = Query(default=25, ge=1, le=100),
    ) -> SupervisorSnapshot:
        require_local_control(request)
        return service.snapshot(event_limit=event_limit)

    @app.get(
        "/v1/supervisor/agents",
        response_model=list[SupervisorAgent],
    )
    def get_supervisor_agents(
        request: Request,
    ) -> list[SupervisorAgent]:
        require_local_control(request)
        return list(service.snapshot(event_limit=1).agents)

    @app.get(
        "/v1/supervisor/events",
        response_model=list[SupervisorEvent],
    )
    def get_supervisor_events(
        request: Request,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> list[SupervisorEvent]:
        require_local_control(request)
        service.reconcile_tasks()
        return list(service.store.recent_events(limit=limit))

    @app.post(
        "/v1/supervisor/agents",
        response_model=SupervisorAgent,
        status_code=status.HTTP_201_CREATED,
    )
    def register_supervisor_agent(
        body: RegisterSupervisorAgentRequest,
        request: Request,
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> SupervisorAgent:
        require_local_control(request)
        require_authenticated(authenticated)

        try:
            return service.register_external_agent(
                agent_id=body.agent_id,
                title=body.title,
                capabilities=body.capabilities,
                dependencies=body.dependencies,
                stale_after_seconds=body.stale_after_seconds,
                metadata=body.metadata,
            )
        except AgentSupervisorError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post(
        "/v1/supervisor/agents/{agent_id}/heartbeat",
        response_model=SupervisorAgent,
    )
    def heartbeat_supervisor_agent(
        agent_id: str,
        body: SupervisorHeartbeatRequest,
        request: Request,
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> SupervisorAgent:
        require_local_control(request)
        require_authenticated(authenticated)

        try:
            return service.heartbeat(agent_id, body)
        except AgentSupervisorError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return service

"""Loopback-only API for unified commitment intelligence."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status

from nexuss.commitments.models import (
    CommitmentHealth,
    PrepareDayRequest,
    WorkdayBrief,
)
from nexuss.commitments.service import (
    CommitmentIntelligenceError,
    CommitmentIntelligenceService,
)


def register_commitment_routes(
    app: FastAPI,
    require_local_control: Callable[[Request], None],
    *,
    service: CommitmentIntelligenceService,
) -> None:
    def authorize(request: Request, *, authenticated: bool) -> None:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_NOT_AUTHENTICATED",
            )

    @app.get(
        "/v1/commitments/health",
        response_model=CommitmentHealth,
    )
    def commitment_health(request: Request) -> CommitmentHealth:
        require_local_control(request)
        return service.health()

    @app.post(
        "/v1/commitments/prepare-day",
        response_model=WorkdayBrief,
    )
    def prepare_day(
        body: PrepareDayRequest,
        request: Request,
        session_id: Annotated[
            UUID, Header(alias="X-Nexuss-Session-ID")
        ],
        authenticated: Annotated[
            bool, Header(alias="X-Nexuss-Session-Authenticated")
        ],
    ) -> WorkdayBrief:
        del session_id
        authorize(request, authenticated=authenticated)
        try:
            return service.prepare_day(body)
        except CommitmentIntelligenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get(
        "/v1/commitments/today",
        response_model=WorkdayBrief,
    )
    def prepare_today(
        request: Request,
        session_id: Annotated[
            UUID, Header(alias="X-Nexuss-Session-ID")
        ],
        authenticated: Annotated[
            bool, Header(alias="X-Nexuss-Session-Authenticated")
        ],
        timezone: str = "Africa/Nairobi",
    ) -> WorkdayBrief:
        del session_id
        authorize(request, authenticated=authenticated)
        try:
            return service.prepare_day(
                PrepareDayRequest(
                    planning_date=datetime.now(UTC).date(),
                    timezone=timezone,
                )
            )
        except CommitmentIntelligenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.


Loopback-only API for deterministic understanding and clarification.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from nexuss.understanding.clarification import ClarificationSessionError
from nexuss.understanding.models import (
    ClarificationAnswer,
    UnderstandingRequest,
    UnderstandingResponse,
)
from nexuss.understanding.service import (
    GoalUnderstandingError,
    GoalUnderstandingService,
)


def register_understanding_routes(
    app: FastAPI,
    require_local_control: Callable[[Request], None],
    *,
    service: GoalUnderstandingService | None = None,
) -> None:
    understanding = service or GoalUnderstandingService.from_environment()

    def authorize(request: Request, authenticated: bool) -> None:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_NOT_AUTHENTICATED",
            )

    @app.get("/v1/understanding/health")
    def understanding_health(request: Request) -> dict[str, object]:
        require_local_control(request)
        return {
            "status": "ready",
            "mode": "p68a_unified_commitment_intelligence",
            "clarification_types": ["yes_no", "single_select"],
            "github_read_only_available": (
                understanding.github_read_only_available
            ),
            "commitment_read_only_available": (
                understanding.commitment_read_only_available
            ),
            "github_write_authority_added": False,
            "google_write_authority_added": False,
            "approval_authority_changed": False,
        }

    @app.post(
        "/v1/understanding/resolve",
        response_model=UnderstandingResponse,
    )
    def resolve_understanding(
        body: UnderstandingRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> UnderstandingResponse:
        authorize(request, authenticated)
        try:
            return understanding.resolve(
                body,
                session_id=session_id,
            )
        except GoalUnderstandingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.post(
        "/v1/understanding/clarifications/{clarification_id}/answer",
        response_model=UnderstandingResponse,
    )
    def answer_understanding_clarification(
        clarification_id: UUID,
        body: ClarificationAnswer,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> UnderstandingResponse:
        authorize(request, authenticated)
        try:
            return understanding.answer_clarification(
                clarification_id,
                body,
                session_id=session_id,
            )
        except (GoalUnderstandingError, ClarificationSessionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.delete(
        "/v1/understanding/clarifications/{clarification_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def cancel_understanding_clarification(
        clarification_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> Response:
        authorize(request, authenticated)
        try:
            understanding.cancel_clarification(
                clarification_id,
                session_id=session_id,
            )
        except GoalUnderstandingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

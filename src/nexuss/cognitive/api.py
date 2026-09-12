"""Authenticated grounded cognitive API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nexuss.cognitive.context import build_cognitive_context
from nexuss.cognitive.models import CognitiveMode
from nexuss.cognitive.receipt import (
    CognitiveProposalEnvelope,
    build_cognitive_receipt,
)
from nexuss.cognitive.service import (
    CognitiveProposalError,
    CognitiveProposalService,
)
from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import (
    EngineeringTaskSpec,
    TaskSensitivity,
    WorkspaceKind,
)
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)


class CognitiveProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    instruction: str = Field(min_length=1, max_length=20_000)
    mode: CognitiveMode = CognitiveMode.ANALYZE


def register_cognitive_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> None:
    @app.post(
        "/v1/cognitive/proposals",
        response_model=CognitiveProposalEnvelope,
        status_code=status.HTTP_200_OK,
    )
    def create_cognitive_proposal(
        proposal_request: CognitiveProposalRequest,
        http_request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        session_authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> CognitiveProposalEnvelope:
        require_local_control(http_request)

        if (
            not session_authenticated
            or session_id != proposal_request.user_session_id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session does not match the request.",
            )

        try:
            connections = EngineeringProviderConnectionService(
                DpapiSecretVault(),
                timeout_seconds=120.0,
            )

            access = connections.deepseek_access()

            if not access.available:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": access.code.value,
                        "message": access.user_message,
                        "fallback": (
                            "No cognitive proposal was generated. "
                            "Nexuss remains operational and no action "
                            "was performed."
                        ),
                    },
                )

            router = connections.build_deepseek_router()
            profile = router.profile("deepseek")

            context = build_cognitive_context(
                provider_status=access.code.value,
            )
            context_summary = context.to_provider_summary()

            task = EngineeringTaskSpec(
                task_id=proposal_request.request_id,
                goal=proposal_request.instruction,
                provider_id="deepseek",
                workspace_kind=WorkspaceKind.LOCAL,
                sensitivity=TaskSensitivity.PRIVATE,
                external_processing_approved=True,
                allowed_tools=(),
                max_rounds=1,
                max_files_changed=1,
                max_runtime_seconds=120,
            )

            cognitive = CognitiveProposalService(
                provider_id="deepseek",
                model=profile.model,
                proposer=lambda request: router.propose(task, request),
            )

            proposal = cognitive.propose(
                instruction=proposal_request.instruction,
                mode=proposal_request.mode,
                context_summary=context_summary,
            )

            receipt = build_cognitive_receipt(
                request_id=proposal_request.request_id,
                instruction=proposal_request.instruction,
                context_summary=context_summary,
                proposal=proposal,
            )

            return CognitiveProposalEnvelope(
                proposal=proposal,
                receipt=receipt,
            )
        except HTTPException:
            raise
        except CognitiveProposalError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                },
            ) from exc
        except EngineeringError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": getattr(
                        exc,
                        "code",
                        "ENGINEERING_PROVIDER_UNAVAILABLE",
                    ),
                    "message": str(exc),
                    "fallback": (
                        "No cognitive proposal was generated. "
                        "Nexuss remains operational and no action "
                        "was performed."
                    ),
                },
            ) from exc

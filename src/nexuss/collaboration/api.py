"""Authenticated API for the Nexuss Collaboration Protocol."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nexuss.capabilities.broker import CapabilityBroker
from nexuss.collaboration.crypto import sha256_json
from nexuss.collaboration.models import (
    ActionPlanPayload,
    ApprovalStatePayload,
    CapabilityLeaseEntry,
    CapabilityLeasePayload,
    CollaborationSession,
    EvidencePayload,
    FinalResponsePayload,
    IntentPayload,
    MessageKind,
    ProtocolMessage,
    StopPayload,
)
from nexuss.collaboration.service import (
    CollaborationProtocolError,
    CollaborationProtocolService,
)
from nexuss.collaboration.store import SQLiteCollaborationStore


class StartCollaborationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    provider_id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=20_000)
    context_summary: str = Field(default="", max_length=50_000)
    privacy_classification: str = Field(
        default="private",
        min_length=1,
        max_length=40,
    )
    maximum_rounds: int = Field(default=6, ge=1, le=20)
    maximum_actions_per_round: int = Field(
        default=8,
        ge=1,
        le=12,
    )


class StartCollaborationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: CollaborationSession
    intent_message: ProtocolMessage
    capability_lease_message: ProtocolMessage


class ProviderTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply_to_message_id: UUID
    kind: MessageKind
    action_plan: ActionPlanPayload | None = None
    final_response: FinalResponsePayload | None = None
    stop: StopPayload | None = None


class NexussTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply_to_message_id: UUID
    kind: MessageKind
    evidence: EvidencePayload | None = None
    approval_state: ApprovalStatePayload | None = None
    stop: StopPayload | None = None


class ProtocolTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session: CollaborationSession
    message: ProtocolMessage


def register_collaboration_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> None:
    service = CollaborationProtocolService(
        store=SQLiteCollaborationStore()
    )

    def validate_session(
        *,
        expected: UUID,
        actual: UUID,
        authenticated: bool,
    ) -> None:
        if not authenticated or expected != actual:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Authenticated session does not match "
                    "the collaboration request."
                ),
            )

    @app.post(
        "/v1/collaboration/sessions",
        response_model=StartCollaborationResponse,
    )
    def start_collaboration(
        body: StartCollaborationRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> StartCollaborationResponse:
        require_local_control(request)
        validate_session(
            expected=body.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )
        broker = CapabilityBroker(
            maximum_actions=body.maximum_actions_per_round
        )
        catalog = broker.catalog()
        lease_entries = tuple(
            CapabilityLeaseEntry(
                capability_id=item.capability_id,
                risk_tier=item.risk_tier,
                approval_policy=item.approval_policy,
                approval_channel=item.approval_channel,
                execution_mode=item.execution_mode,
                provider_can_request=item.provider_can_request,
            )
            for item in catalog
            if item.provider_can_request
        )
        now = datetime.now(UTC)
        intent = IntentPayload(
            instruction=body.instruction,
            instruction_sha256=hashlib.sha256(
                body.instruction.encode("utf-8")
            ).hexdigest(),
            context_sha256=hashlib.sha256(
                body.context_summary.encode("utf-8")
            ).hexdigest(),
            privacy_classification=(
                body.privacy_classification
            ),
            maximum_rounds=body.maximum_rounds,
            maximum_actions_per_round=(
                body.maximum_actions_per_round
            ),
        )
        lease = CapabilityLeasePayload(
            catalog_sha256=sha256_json(
                [item.model_dump(mode="json") for item in lease_entries]
            ),
            lease_id=uuid4(),
            expires_at=now + timedelta(minutes=15),
            capabilities=lease_entries,
        )
        try:
            session, intent_message, lease_message = (
                service.create_session(
                    request_id=body.request_id,
                    user_session_id=body.user_session_id,
                    provider_id=body.provider_id,
                    model=body.model,
                    intent=intent,
                    lease=lease,
                )
            )
        except CollaborationProtocolError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

        return StartCollaborationResponse(
            session=session,
            intent_message=intent_message,
            capability_lease_message=lease_message,
        )

    @app.post(
        "/v1/collaboration/sessions/{collaboration_id}/provider",
        response_model=ProtocolTurnResponse,
    )
    def provider_turn(
        collaboration_id: UUID,
        body: ProviderTurnRequest,
        request: Request,
    ) -> ProtocolTurnResponse:
        require_local_control(request)
        payload = (
            body.action_plan
            if body.kind is MessageKind.ACTION_PLAN
            else (
                body.final_response
                if body.kind is MessageKind.FINAL_RESPONSE
                else body.stop
            )
        )
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message kind and payload do not match.",
            )
        try:
            session, message = service.accept_provider_message(
                session_id=collaboration_id,
                kind=body.kind,
                payload=payload,
                reply_to_message_id=body.reply_to_message_id,
            )
        except CollaborationProtocolError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return ProtocolTurnResponse(
            session=session,
            message=message,
        )

    @app.post(
        "/v1/collaboration/sessions/{collaboration_id}/nexuss",
        response_model=ProtocolTurnResponse,
    )
    def nexuss_turn(
        collaboration_id: UUID,
        body: NexussTurnRequest,
        request: Request,
    ) -> ProtocolTurnResponse:
        require_local_control(request)
        payload = (
            body.evidence
            if body.kind is MessageKind.EVIDENCE
            else (
                body.approval_state
                if body.kind is MessageKind.APPROVAL_STATE
                else body.stop
            )
        )
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message kind and payload do not match.",
            )
        try:
            session, message = service.send_nexuss_message(
                session_id=collaboration_id,
                kind=body.kind,
                payload=payload,
                reply_to_message_id=body.reply_to_message_id,
            )
        except CollaborationProtocolError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return ProtocolTurnResponse(
            session=session,
            message=message,
        )

    @app.get(
        "/v1/collaboration/sessions/{collaboration_id}",
    )
    def get_collaboration(
        collaboration_id: UUID,
        request: Request,
    ) -> dict[str, object]:
        require_local_control(request)
        session = service._store.get_session(collaboration_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collaboration session was not found.",
            )
        try:
            messages = service.transcript(collaboration_id)
        except CollaborationProtocolError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return {
            "session": session.model_dump(mode="json"),
            "messages": [
                message.model_dump(mode="json")
                for message in messages
            ],
            "provider_direct_execution": False,
            "nexuss_retains_final_authority": True,
        }

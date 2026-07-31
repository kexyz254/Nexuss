"""FastAPI routes for the P6.7A trusted mobile communication fabric."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, status

from nexuss.mobile.gateway import MobileApprovalGateway, MobilePairingError
from nexuss.mobile_fabric.assertion import (
    AssertionInput,
    DeviceAssertionVerifier,
    MobileAssertionError,
    sha256_bytes,
)
from nexuss.mobile_fabric.models import (
    MobileActionDecision,
    MobileActionEvidence,
    MobileActionPrepareRequest,
    MobileActionView,
    MobileAttentionSummary,
    MobileCapabilityMatrix,
    MobileFeedSnapshot,
    MobileSignalBatch,
    MobileSignalIngestResult,
    MobileSource,
)
from nexuss.mobile_fabric.service import MobileFabricError, MobileFabricService

_EMPTY_BODY_SHA256 = sha256_bytes(b"")


def register_mobile_fabric_routes(
    app: FastAPI,
    require_local_control: Callable[[Request], None],
    *,
    mobile_gateway: MobileApprovalGateway,
    service: MobileFabricService | None = None,
    assertions: DeviceAssertionVerifier | None = None,
) -> MobileFabricService:
    fabric = service or MobileFabricService()
    assertion_verifier = assertions or DeviceAssertionVerifier()

    def authorize_local(
        request: Request,
        *,
        session_id: UUID,
        authenticated: bool,
    ) -> None:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_NOT_AUTHENTICATED",
            )
        if not any(
            device.session_id == session_id
            for device in mobile_gateway.list_devices()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TRUSTED_MOBILE_DEVICE_REQUIRED",
            )

    def authorize_device(
        *,
        device_id: UUID,
        device_token: str,
        method: str,
        path: str,
        timestamp: str,
        nonce: str,
        body_sha256: str,
        signature: str,
        canonical_body: bytes,
    ) -> UUID:
        try:
            session_id = mobile_gateway.authenticate(device_id, device_token)
        except MobilePairingError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        computed_hash = sha256_bytes(canonical_body)
        if computed_hash != body_sha256.casefold():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="MOBILE_ASSERTION_BODY_HASH_MISMATCH",
            )
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
            assertion_verifier.verify(
                device_token=device_token,
                assertion=AssertionInput(
                    method=method,
                    path=path,
                    timestamp=parsed_timestamp,
                    nonce=nonce,
                    body_sha256=body_sha256.casefold(),
                ),
                signature=signature,
            )
        except (ValueError, MobileAssertionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        return session_id

    def handle_error(exc: MobileFabricError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        )

    @app.get("/v1/mobile-fabric/health")
    def mobile_fabric_health(request: Request) -> dict[str, object]:
        require_local_control(request)
        return {
            "status": "ready",
            "mode": "p67a_trusted_mobile_communication_fabric",
            "trusted_device_required": True,
            "device_assertions": "hmac_sha256",
            "notification_access": True,
            "private_app_database_access": False,
            "accessibility_automation": False,
            "external_actions_require_approval": True,
        }

    @app.get(
        "/v1/mobile-fabric/capabilities",
        response_model=MobileCapabilityMatrix,
    )
    def mobile_capabilities(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> MobileCapabilityMatrix:
        authorize_local(
            request,
            session_id=session_id,
            authenticated=authenticated,
        )
        return fabric.capabilities()

    @app.post(
        "/v1/mobile-fabric/signals",
        response_model=MobileSignalIngestResult,
    )
    async def ingest_mobile_signals(
        body: MobileSignalBatch,
        request: Request,
        device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
        device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
        assertion_timestamp: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Timestamp"),
        ],
        assertion_nonce: Annotated[str, Header(alias="X-Nexuss-Mobile-Nonce")],
        body_sha256: Annotated[str, Header(alias="X-Nexuss-Mobile-Body-SHA256")],
        assertion_signature: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Assertion"),
        ],
    ) -> MobileSignalIngestResult:
        authorize_device(
            device_id=device_id,
            device_token=device_token,
            method="POST",
            path="/v1/mobile-fabric/signals",
            timestamp=assertion_timestamp,
            nonce=assertion_nonce,
            body_sha256=body_sha256,
            signature=assertion_signature,
            canonical_body=await request.body(),
        )
        return fabric.ingest(device_id=device_id, batch=body)

    @app.get(
        "/v1/mobile-fabric/feed",
        response_model=MobileFeedSnapshot,
    )
    def read_mobile_feed(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
        after_cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        source: MobileSource | None = None,
    ) -> MobileFeedSnapshot:
        authorize_local(
            request,
            session_id=session_id,
            authenticated=authenticated,
        )
        try:
            return fabric.feed(
                after_cursor=after_cursor,
                limit=limit,
                source=source,
            )
        except MobileFabricError as exc:
            raise handle_error(exc) from exc

    @app.get(
        "/v1/mobile-fabric/attention",
        response_model=MobileAttentionSummary,
    )
    def mobile_attention_summary(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> MobileAttentionSummary:
        authorize_local(
            request,
            session_id=session_id,
            authenticated=authenticated,
        )
        return fabric.attention_summary()

    @app.post(
        "/v1/mobile-fabric/actions/prepare",
        response_model=MobileActionView,
    )
    def prepare_mobile_action(
        body: MobileActionPrepareRequest,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> MobileActionView:
        authorize_local(
            request,
            session_id=session_id,
            authenticated=authenticated,
        )
        if not any(
            device.device_id == body.device_id and device.session_id == session_id
            for device in mobile_gateway.list_devices()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="MOBILE_ACTION_DEVICE_NOT_IN_SESSION",
            )
        try:
            return fabric.prepare_action(body)
        except MobileFabricError as exc:
            raise handle_error(exc) from exc

    @app.get(
        "/v1/mobile-fabric/actions/pending",
        response_model=list[MobileActionView],
    )
    def pending_mobile_actions(
        device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
        device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
        assertion_timestamp: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Timestamp"),
        ],
        assertion_nonce: Annotated[str, Header(alias="X-Nexuss-Mobile-Nonce")],
        body_sha256: Annotated[str, Header(alias="X-Nexuss-Mobile-Body-SHA256")],
        assertion_signature: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Assertion"),
        ],
    ) -> list[MobileActionView]:
        authorize_device(
            device_id=device_id,
            device_token=device_token,
            method="GET",
            path="/v1/mobile-fabric/actions/pending",
            timestamp=assertion_timestamp,
            nonce=assertion_nonce,
            body_sha256=body_sha256,
            signature=assertion_signature,
            canonical_body=b"",
        )
        if body_sha256.casefold() != _EMPTY_BODY_SHA256:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="MOBILE_EMPTY_BODY_HASH_REQUIRED",
            )
        return list(fabric.pending(device_id))

    @app.post(
        "/v1/mobile-fabric/actions/{action_id}/decision",
        response_model=MobileActionView,
    )
    async def decide_mobile_action(
        action_id: UUID,
        body: MobileActionDecision,
        request: Request,
        device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
        device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
        assertion_timestamp: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Timestamp"),
        ],
        assertion_nonce: Annotated[str, Header(alias="X-Nexuss-Mobile-Nonce")],
        body_sha256: Annotated[str, Header(alias="X-Nexuss-Mobile-Body-SHA256")],
        assertion_signature: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Assertion"),
        ],
    ) -> MobileActionView:
        path = f"/v1/mobile-fabric/actions/{action_id}/decision"
        authorize_device(
            device_id=device_id,
            device_token=device_token,
            method="POST",
            path=path,
            timestamp=assertion_timestamp,
            nonce=assertion_nonce,
            body_sha256=body_sha256,
            signature=assertion_signature,
            canonical_body=await request.body(),
        )
        try:
            return fabric.decide(
                device_id=device_id,
                action_id=action_id,
                decision=body,
            )
        except MobileFabricError as exc:
            raise handle_error(exc) from exc

    @app.get(
        "/v1/mobile-fabric/actions/approved",
        response_model=list[MobileActionView],
    )
    def approved_mobile_actions(
        device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
        device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
        assertion_timestamp: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Timestamp"),
        ],
        assertion_nonce: Annotated[str, Header(alias="X-Nexuss-Mobile-Nonce")],
        body_sha256: Annotated[str, Header(alias="X-Nexuss-Mobile-Body-SHA256")],
        assertion_signature: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Assertion"),
        ],
    ) -> list[MobileActionView]:
        authorize_device(
            device_id=device_id,
            device_token=device_token,
            method="GET",
            path="/v1/mobile-fabric/actions/approved",
            timestamp=assertion_timestamp,
            nonce=assertion_nonce,
            body_sha256=body_sha256,
            signature=assertion_signature,
            canonical_body=b"",
        )
        return list(fabric.approved(device_id))

    @app.post(
        "/v1/mobile-fabric/actions/{action_id}/evidence",
        response_model=MobileActionView,
    )
    async def record_mobile_action_evidence(
        action_id: UUID,
        body: MobileActionEvidence,
        request: Request,
        device_id: Annotated[UUID, Header(alias="X-Nexuss-Mobile-Device-ID")],
        device_token: Annotated[str, Header(alias="X-Nexuss-Mobile-Token")],
        assertion_timestamp: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Timestamp"),
        ],
        assertion_nonce: Annotated[str, Header(alias="X-Nexuss-Mobile-Nonce")],
        body_sha256: Annotated[str, Header(alias="X-Nexuss-Mobile-Body-SHA256")],
        assertion_signature: Annotated[
            str,
            Header(alias="X-Nexuss-Mobile-Assertion"),
        ],
    ) -> MobileActionView:
        path = f"/v1/mobile-fabric/actions/{action_id}/evidence"
        authorize_device(
            device_id=device_id,
            device_token=device_token,
            method="POST",
            path=path,
            timestamp=assertion_timestamp,
            nonce=assertion_nonce,
            body_sha256=body_sha256,
            signature=assertion_signature,
            canonical_body=await request.body(),
        )
        try:
            return fabric.record_evidence(
                device_id=device_id,
                action_id=action_id,
                evidence=body,
            )
        except MobileFabricError as exc:
            raise handle_error(exc) from exc

    return fabric

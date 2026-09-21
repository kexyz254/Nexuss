"""Authenticated API for the canonical Nexuss interaction runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)

from nexuss.ai.connections import (
    AIProviderConnectionError,
    AIProviderConnectionResolver,
)
from nexuss.ai.registry import (
    AIProviderRegistryError,
    default_provider_registry,
)
from nexuss.conversation.router import ConversationRoutingError
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.engineering.errors import EngineeringError
from nexuss.interactions.models import (
    InteractionPresentation,
    InteractionRequest,
    InteractionResponse,
    SaveConversationRequest,
    SaveConversationResponse,
)
from nexuss.interactions.service import (
    UnifiedInteractionError,
    UnifiedInteractionService,
)
from nexuss.interactions.store import SQLiteInteractionStore
from nexuss.interactions.progress import ProgressHub, reporting


def register_interaction_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
    core_service: object,
) -> None:
    conversation_store = SQLiteConversationStore()
    interaction_store = SQLiteInteractionStore()
    progress = ProgressHub()
    service = UnifiedInteractionService(
        providers=default_provider_registry(),
        resolver=AIProviderConnectionResolver(),
        conversation_store=conversation_store,
        interaction_store=interaction_store,
        core_service=core_service,
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
                    "Authenticated session does not match the "
                    "interaction request."
                ),
            )

    @app.post(
        "/v1/interactions",
        response_model=InteractionResponse,
    )
    def create_interaction(
        body: InteractionRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> InteractionResponse:
        require_local_control(request)
        validate_session(
            expected=body.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        conversation = conversation_store.get(body.conversation_id)
        if (
            conversation is None
            or conversation.user_session_id != session_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        try:
            progress.start(
                body.request_id,
                session_id,
                body.conversation_id,
            )
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Request not found",
            ) from None
        except RuntimeError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Request is already running or progress capacity is full"
                ),
            ) from None

        try:
            with reporting(
                lambda kind, state, detail: progress.append(
                    body.request_id,
                    kind,
                    state,
                    detail,
                )
            ):
                result = service.interact(body)
            progress.finish(body.request_id, result.state.value)
            return result
        except (
            AIProviderRegistryError,
            AIProviderConnectionError,
            ConversationRoutingError,
            EngineeringError,
            UnifiedInteractionError,
        ) as exc:
            progress.finish(body.request_id, "failed")
            code = getattr(
                exc,
                "code",
                "INTERACTION_FAILED_CLOSED",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": code,
                    "message": str(exc),
                    "nexuss_retains_final_authority": True,
                },
            ) from exc

        except Exception:
            progress.finish(body.request_id, "failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Interaction failed; inspect the retained workflow "
                    "before retrying"
                ),
            ) from None

    @app.get("/v1/interactions/progress/{request_id}")
    def get_progress(
        request_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> dict[str, object]:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session is required",
            )
        try:
            return progress.get(request_id, session_id)
        except LookupError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Progress not found",
            ) from None

    @app.get(
        "/v1/interactions/{interaction_id}/presentation",
        response_model=InteractionPresentation,
    )
    def get_interaction_presentation(
        interaction_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> InteractionPresentation:
        require_local_control(request)

        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session is required.",
            )

        try:
            return service.presentation(
                interaction_id=interaction_id,
                user_session_id=session_id,
            )
        except UnifiedInteractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post(
        "/v1/interactions/{interaction_id}/refresh",
        response_model=InteractionResponse,
    )
    def refresh_interaction(
        interaction_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> InteractionResponse:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session is required.",
            )
        try:
            return service.refresh(
                interaction_id=interaction_id,
                user_session_id=session_id,
            )
        except UnifiedInteractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.get(
        "/v1/interactions/{interaction_id}",
        response_model=InteractionResponse,
    )
    def get_interaction(
        interaction_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> InteractionResponse:
        require_local_control(request)
        response = interaction_store.get(interaction_id)

        if response is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction was not found.",
            )

        validate_session(
            expected=response.conversation.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )
        return response

    @app.get("/v1/interactions")
    def list_interactions(
        request: Request,
        conversation_id: Annotated[
            UUID,
            Query(alias="conversation_id"),
        ],
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
        limit: Annotated[int, Query(ge=1, le=30)] = 12,
    ) -> dict[str, object]:
        require_local_control(request)
        conversation = conversation_store.get(conversation_id)

        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        validate_session(
            expected=conversation.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        return {
            "interactions": [
                item.model_dump(mode="json")
                for item in interaction_store.recent(
                    conversation_id,
                    limit=limit,
                )
            ]
        }

    @app.post(
        "/v1/interactions/conversations/{conversation_id}/save",
        response_model=SaveConversationResponse,
    )
    def save_conversation(
        conversation_id: UUID,
        body: SaveConversationRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> SaveConversationResponse:
        require_local_control(request)
        validate_session(
            expected=body.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        try:
            return service.save_conversation_as_note(
                conversation_id=conversation_id,
                request_id=body.request_id,
                user_session_id=body.user_session_id,
                note_title=body.note_title,
            )
        except (UnifiedInteractionError, PermissionError, LookupError) as exc:
            code = getattr(
                exc,
                "code",
                "SESSION_NOTE_PREPARATION_FAILED",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": code,
                    "message": str(exc),
                    "automatic_memory_promotion": False,
                },
            ) from exc

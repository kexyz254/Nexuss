"""Authenticated persistent conversation and smart-routing API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from nexuss.ai.connections import (
    AIProviderConnectionError,
    AIProviderConnectionResolver,
)
from nexuss.ai.registry import (
    AIProviderRegistryError,
    default_provider_registry,
)
from nexuss.cognitive.models import CognitiveMode
from nexuss.engineering.errors import EngineeringError
from nexuss.conversation.models import (
    ConversationHistoryResponse,
    ConversationRoute,
    ConversationTurnRequest,
    ConversationTurnResponse,
    CreateConversationRequest,
    MessageRole,
    RenameConversationRequest,)
from nexuss.conversation.router import (
    ConversationRouterService,
    ConversationRoutingError,
)
from nexuss.conversation.security import sanitize_text
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.conversation.trading import handle_trading_chat


def register_conversation_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> None:
    store = SQLiteConversationStore()
    providers = default_provider_registry()

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
                    "conversation."
                ),
            )

    @app.post(
        "/v1/conversations",
        response_model=ConversationHistoryResponse,
    )
    def create_conversation(
        body: CreateConversationRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ConversationHistoryResponse:
        require_local_control(request)
        validate_session(
            expected=body.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        try:
            profile = providers.select(
                provider_id=body.provider_id,
                mode=CognitiveMode.ANALYZE,
            )
        except AIProviderRegistryError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

        model = (
            "deepseek-v4-pro"
            if profile.provider_id == "deepseek"
            else profile.display_name
        )
        try:
            record = store.create(
                conversation_id=body.conversation_id,
                user_session_id=body.user_session_id,
                title=body.title,
                provider_id=profile.provider_id,
                model=model,
                continuation_token=body.continuation_token,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CONVERSATION_CONTINUATION_TOKEN_INVALID",
                    "message": str(exc),
                },
            ) from exc

        return ConversationHistoryResponse(
            conversation=record,
            messages=store.messages(record.conversation_id),
        )

    @app.get(
        "/v1/conversations/{conversation_id}",
        response_model=ConversationHistoryResponse,
    )
    def get_conversation(
        conversation_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ConversationHistoryResponse:
        require_local_control(request)
        record = store.get(conversation_id)

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        validate_session(
            expected=record.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )
        return ConversationHistoryResponse(
            conversation=record,
            messages=store.messages(conversation_id),
        )

    @app.get("/v1/conversations")
    def list_conversations(
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
                detail="Authenticated session is required.",
            )

        return {
            "conversations": [
                item.model_dump(mode="json")
                for item in store.list_for_session(session_id)
            ]
        }

    @app.patch(
        "/v1/conversations/{conversation_id}",
        response_model=ConversationHistoryResponse,
    )
    def rename_conversation(
        conversation_id: UUID,
        body: RenameConversationRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ConversationHistoryResponse:
        require_local_control(request)
        record = store.get(conversation_id)

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        validate_session(
            expected=record.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        renamed = store.rename(
            conversation_id,
            title=body.title,
        )

        if renamed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        return ConversationHistoryResponse(
            conversation=renamed,
            messages=store.messages(conversation_id),
        )

    @app.delete(
        "/v1/conversations/{conversation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_conversation(
        conversation_id: UUID,
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
        require_local_control(request)
        record = store.get(conversation_id)

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        validate_session(
            expected=record.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        store.delete(conversation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/v1/conversations/{conversation_id}/turns",        response_model=ConversationTurnResponse,
    )
    def create_turn(
        conversation_id: UUID,
        body: ConversationTurnRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ConversationTurnResponse:
        require_local_control(request)
        record = store.get(conversation_id)

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )

        validate_session(
            expected=record.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )
        validate_session(
            expected=body.user_session_id,
            actual=session_id,
            authenticated=authenticated,
        )

        sanitized = sanitize_text(body.text)

        trading = handle_trading_chat(sanitized.value)
        if trading is not None:
            response_text = trading.text
            if sanitized.redactions:
                response_text += "\n\nNexuss removed credential-shaped content before persistence."
            user_message, assistant_message, updated = store.append_turn(
                conversation_id=conversation_id,
                user_text=sanitized.value,
                assistant_text=response_text,
                route=ConversationRoute.CHAT,
                provider_id="nexuss-tas",
                model="verified-evidence-v1",
                pending_action=None,
                pending_capability_hint=None,
            )
            return ConversationTurnResponse(
                conversation=updated, user_message=user_message,
                assistant_message=assistant_message, route=ConversationRoute.CHAT,
                provider_id="nexuss-tas", model="verified-evidence-v1",
                tools_executed=trading.tools_executed,
            )

        try:
            profile = providers.select(
                provider_id=body.provider_id,
                mode=CognitiveMode.ANALYZE,
            )
            resolved = AIProviderConnectionResolver().resolve(
                profile=profile,
                request_id=body.request_id,
                instruction=sanitized.value,
                external_processing_approved=(
                    body.external_processing_approved
                ),
            )
            router = ConversationRouterService(
                provider_id=profile.provider_id,
                model=resolved.model,
                proposer=resolved.proposer,
            )
            classification = router.route(
                user_text=sanitized.value,
                conversation_context=store.recent_context(
                    conversation_id
                ),
                pending_action=record.pending_action,
                pending_capability_hint=(
                    record.pending_capability_hint
                ),
            )
        except (
            AIProviderRegistryError,
            AIProviderConnectionError,
            ConversationRoutingError,
            EngineeringError,
        ) as exc:
            code = getattr(
                exc,
                "code",
                "CONVERSATION_PROVIDER_FAILED",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": code, "message": str(exc)},
            ) from exc

        response_text = classification.response

        if sanitized.redactions:
            response_text += (
                "\n\nNexuss removed credential-shaped content "
                "before persistence and external processing."
            )

        pending_action = None
        pending_capability_hint = None

        if classification.route is ConversationRoute.CLARIFICATION:
            pending_action = (
                record.pending_action or sanitized.value
            )
            pending_capability_hint = (
                classification.capability_hint
            )

        user_message, assistant_message, updated = (
            store.append_turn(
                conversation_id=conversation_id,
                user_text=sanitized.value,
                assistant_text=response_text,
                route=classification.route,
                provider_id=profile.provider_id,
                model=resolved.model,
                pending_action=pending_action,
                pending_capability_hint=(
                    pending_capability_hint
                ),
            )
        )

        return ConversationTurnResponse(
            conversation=updated,
            user_message=user_message,
            assistant_message=assistant_message,
            route=classification.route,
            action_instruction=classification.action_instruction,
            clarification_question=(
                classification.clarification_question
            ),
            capability_hint=classification.capability_hint,
            provider_id=profile.provider_id,
            model=resolved.model,
        )

"""One canonical interaction pipeline for chat and governed actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.ai.connections import AIProviderConnectionResolver
from nexuss.ai.registry import AIProviderRegistry
from nexuss.cognitive.models import CognitiveMode
from nexuss.conversation.models import (
    ConversationRoute,
    MessageRole,
)
from nexuss.conversation.router import ConversationRouterService
from nexuss.conversation.security import sanitize_text
from nexuss.conversation.stabilization import (
    deterministic_route_result,
)
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.conversation.trading import handle_trading_chat
from nexuss.conversation.models import RouteClassification
from nexuss.domain.models import Channel, IdentitySession, TaskRequest
from nexuss.interactions.journal import build_session_markdown
from nexuss.interactions.models import (
    InteractionEvent,
    InteractionKind,
    InteractionPresentation,
    InteractionRequest,
    InteractionResponse,
    InteractionState,
    SaveConversationResponse,
)
from nexuss.interactions.store import SQLiteInteractionStore


class UnifiedInteractionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _task_state(task: object) -> str:
    return str(getattr(task, "state", "unknown"))


def _interaction_state_for_core_task(state_text: str) -> InteractionState:
    if state_text == "completed":
        return InteractionState.COMPLETED
    if state_text == "awaiting_approval":
        return InteractionState.AWAITING_APPROVAL
    if state_text == "denied":
        return InteractionState.DENIED
    if state_text in {"received", "planned", "approved", "executing", "verifying"}:
        return InteractionState.RESPONDED
    return InteractionState.FAILED


def _approval_id(task: object) -> UUID | None:
    approval = getattr(task, "approval", None)

    if approval is None:
        return None

    value = getattr(approval, "approval_id", None)

    if isinstance(value, UUID):
        return value

    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _receipt_id(receipt: object | None) -> UUID | None:
    if receipt is None:
        return None

    value = getattr(receipt, "receipt_id", None)

    if isinstance(value, UUID):
        return value

    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _evidence_count(task: object) -> int:
    total = 0

    for result in getattr(task, "results", ()) or ():
        total += len(getattr(result, "evidence", ()) or ())

    return total


def _first_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    if isinstance(value, dict):
        for key in (
            "message",
            "summary",
            "answer",
            "text",
            "display_text",
        ):
            candidate = value.get(key)

            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    return None


def _task_display_text(
    task: object,
    *,
    fallback: str,
) -> str:
    for attribute in (
        "display_text",
        "response",
        "message",
        "summary",
    ):
        candidate = _first_text(getattr(task, attribute, None))

        if candidate:
            return candidate

    for result in getattr(task, "results", ()) or ():
        for attribute in (
            "display_text",
            "output",
            "result",
            "message",
            "summary",
        ):
            candidate = _first_text(
                getattr(result, attribute, None)
            )

            if candidate:
                return candidate

    state = _task_state(task)

    if state == "awaiting_approval":
        return (
            "The action is prepared and waiting for your exact "
            "approval."
        )

    if state == "completed":
        return (
            fallback
            or "Nexuss completed the action and verified its evidence."
        )

    if state == "denied":
        return "Nexuss denied the action under the active policy."

    if state in {"received", "planned", "approved", "executing"}:
        return (
            "Nexuss created the governed task and started bounded execution. "
            "Follow Task Runtime or Prompt-to-Build progress for live status."
        )

    if state == "verifying":
        return "Nexuss is verifying the governed task evidence."

    return (
        "Nexuss could not complete the requested action. "
        "Review Action Control for the verified failure state."
    )


# P6.14.1 ENGINEERING CONTINUATION
_ENGINEERING_CONTINUATION_MARKERS = (
    "start it",
    "continue",
    "proceed",
    "go ahead",
    "create a governed task",
    "create the governed task",
    "run the task",
    "run it",
    "begin the task",
    "begin it",
)
_ENGINEERING_CONTINUATION_BLOCKERS = (
    "do not continue",
    "don't continue",
    "dont continue",
    "do not proceed",
    "don't proceed",
    "dont proceed",
    "cancel",
    "stop",
)
_PREPARED_BUILD = re.compile(
    r"(Nexuss,\s*build\s+yourself:\s*.+)",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_recent_engineering_continuation(
    current_text: str,
    messages: tuple[object, ...],
    *,
    now: datetime,
) -> str | None:
    normalized = " ".join(current_text.casefold().split())
    if len(normalized) > 220:
        return None
    if any(
        blocker in normalized
        for blocker in _ENGINEERING_CONTINUATION_BLOCKERS
    ):
        return None
    if not any(
        marker in normalized
        for marker in _ENGINEERING_CONTINUATION_MARKERS
    ):
        return None

    for message in reversed(messages[-24:]):
        created_at = getattr(message, "created_at", None)
        if created_at is not None:
            try:
                if now - created_at > timedelta(minutes=45):
                    break
            except TypeError:
                continue
        message_text = str(getattr(message, "text", "") or "").strip()
        match = _PREPARED_BUILD.search(message_text)
        if not match:
            continue
        command = match.group(1).strip()
        return command[:20_000].rstrip()
    return None


class UnifiedInteractionService:
    def __init__(
        self,
        *,
        providers: AIProviderRegistry,
        resolver: AIProviderConnectionResolver,
        conversation_store: SQLiteConversationStore,
        interaction_store: SQLiteInteractionStore,
        core_service: object,
    ) -> None:
        self._providers = providers
        self._resolver = resolver
        self._conversations = conversation_store
        self._interactions = interaction_store
        self._core = core_service

    def interact(
        self,
        request: InteractionRequest,
    ) -> InteractionResponse:
        existing = self._interactions.get_by_request(
            request.request_id
        )

        if existing is not None:
            return existing

        conversation = self._conversations.get(
            request.conversation_id
        )

        if conversation is None:
            raise UnifiedInteractionError(
                "INTERACTION_CONVERSATION_NOT_FOUND",
                "The persistent conversation was not found.",
            )

        if conversation.user_session_id != request.user_session_id:
            raise UnifiedInteractionError(
                "INTERACTION_SESSION_MISMATCH",
                "The conversation belongs to another session.",
            )

        sanitized = sanitize_text(request.text)
        now = datetime.now(UTC)
        events: list[InteractionEvent] = []

        def event(
            event_type: str,
            state: str,
            detail: str,
        ) -> None:
            events.append(
                InteractionEvent(
                    sequence=len(events) + 1,
                    event_type=event_type,
                    state=state,
                    detail=detail,
                    occurred_at=datetime.now(UTC),
                )
            )

        event(
            "interaction_received",
            "received",
            "Authenticated user interaction entered the unified runtime.",
        )

        routing_text = sanitized.value
        continuation = _resolve_recent_engineering_continuation(
            sanitized.value,
            self._conversations.messages(
                request.conversation_id,
                limit=500,
            ),
            now=datetime.now(UTC),
        )
        if continuation is not None:
            routing_text = continuation

        def tas_proposer():
            profile = self._providers.select(provider_id=request.provider_id, mode=CognitiveMode.ANALYZE)
            return self._resolver.resolve(profile=profile, request_id=request.request_id,
                instruction=sanitized.value,
                external_processing_approved=request.external_processing_approved).proposer

        trading = handle_trading_chat(sanitized.value, owner=f"{request.user_session_id}:{request.conversation_id}",
                                     proposer_factory=tas_proposer)
        deterministic = deterministic_route_result(
            routing_text
        ) if trading is None else None

        if trading is not None:
            classification = RouteClassification(
                route=ConversationRoute.CHAT, response=trading.text, confidence=1.0,
            )
            route_provider_id = "nexuss-tas"
            route_model = "verified-evidence-v1"
            route_source = "authenticated_tas_evidence"
            event("tas_evidence", "observed", f"Completed {trading.tools_executed} read operations; no TAS writes.")
        elif deterministic is not None:
            classification = deterministic.classification
            route_provider_id = deterministic.provider_id
            route_model = deterministic.model
            route_source = deterministic.source
        else:
            profile = self._providers.select(
                provider_id=request.provider_id,
                mode=CognitiveMode.ANALYZE,
            )
            resolved = self._resolver.resolve(
                profile=profile,
                request_id=request.request_id,
                instruction=routing_text,
                external_processing_approved=(
                    request.external_processing_approved
                ),
            )
            route_provider_id = profile.provider_id
            route_model = resolved.model
            router = ConversationRouterService(
                provider_id=route_provider_id,
                model=route_model,
                proposer=resolved.proposer,
            )
            classification = router.route(
                user_text=routing_text,
                conversation_context=(
                    self._conversations.recent_context(
                        request.conversation_id
                    )
                ),
                pending_action=conversation.pending_action,
                pending_capability_hint=(
                    conversation.pending_capability_hint
                ),
            )
            route_source = "provider_assisted_router"

        event(
            "intent_classified",
            "planned",
            (
                "The unified conversation router classified the turn as "
                f"{classification.route.value} via {route_source}; "
                "Nexuss retained execution authority."
            ),
        )

        interaction_id = uuid5(
            NAMESPACE_URL,
            f"nexuss:interaction:{request.request_id}",
        )
        kind = InteractionKind(classification.route.value)

        if classification.route is ConversationRoute.CHAT:
            display = classification.response
            if sanitized.redactions:
                display += (
                    "\n\nNexuss redacted credential-shaped content "
                    "before persistence and external processing."
                )

            user_message, assistant_message, conversation = (
                self._conversations.append_turn(
                    conversation_id=request.conversation_id,
                    user_text=sanitized.value,
                    assistant_text=display,
                    route=classification.route,
                    provider_id=route_provider_id,
                    model=route_model,
                    pending_action=None,
                    pending_capability_hint=None,
                )
            )
            event(
                "conversation_saved",
                "completed",
                "The direct chat response was saved to the local journal.",
            )
            response = InteractionResponse(
                interaction_id=interaction_id,
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                kind=kind,
                state=InteractionState.RESPONDED,
                display_text=display,
                provider_id=route_provider_id,
                model=route_model,
                conversation=conversation,
                user_message=user_message,
                assistant_message=assistant_message,
                events=tuple(events),
                created_at=now,
                updated_at=datetime.now(UTC),
            )
            self._interactions.save(response)
            return response

        if classification.route is ConversationRoute.CLARIFICATION:
            question = (
                classification.clarification_question
                or classification.response
            )
            pending_action = (
                conversation.pending_action or sanitized.value
            )
            user_message, assistant_message, conversation = (
                self._conversations.append_turn(
                    conversation_id=request.conversation_id,
                    user_text=sanitized.value,
                    assistant_text=question,
                    route=classification.route,
                    provider_id=route_provider_id,
                    model=route_model,
                    pending_action=pending_action,
                    pending_capability_hint=(
                        classification.capability_hint
                    ),
                )
            )
            event(
                "target_clarification_requested",
                "responded",
                (
                    "Nexuss asked one targeted question and preserved "
                    "the pending action."
                ),
            )
            response = InteractionResponse(
                interaction_id=interaction_id,
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                kind=kind,
                state=InteractionState.RESPONDED,
                display_text=question,
                capability_hint=classification.capability_hint,
                provider_id=route_provider_id,
                model=route_model,
                conversation=conversation,
                user_message=user_message,
                assistant_message=assistant_message,
                events=tuple(events),
                created_at=now,
                updated_at=datetime.now(UTC),
            )
            self._interactions.save(response)
            return response

        instruction = classification.action_instruction

        if not instruction:
            raise UnifiedInteractionError(
                "INTERACTION_ACTION_INSTRUCTION_MISSING",
                "The action route did not contain an exact instruction.",
            )

        event(
            "capability_dispatch_started",
            "executing",
            (
                "The resolved instruction entered Nexuss Core without "
                "being shown as a second user message."
            ),
        )
        identity = IdentitySession(
            session_id=request.user_session_id,
            authenticated=True,
        )
        task_request = TaskRequest(
            request_id=request.request_id,
            channel=Channel.TEXT,
            utterance=instruction,
            user_session_id=request.user_session_id,
            target_devices=[],
            requested_at=datetime.now(UTC),
            client_context={
                "source": "unified_interaction_runtime",
                "interaction_id": str(interaction_id),
                "conversation_id": str(request.conversation_id),
                "original_user_text": sanitized.value,
                "resolved_instruction": instruction,
            },
        )
        try:
            task = self._core.create_task(task_request, identity)
        except Exception as exc:
            raise UnifiedInteractionError(
                "INTERACTION_CORE_DISPATCH_FAILED",
                (
                    "Nexuss Core could not create the governed task. "
                    "No action was executed."
                ),
            ) from exc

        state_text = _task_state(task)
        approval = _approval_id(task)
        receipt = None

        try:
            receipt = self._core.get_receipt(task.task_id)
        except Exception:
            receipt = None

        state = _interaction_state_for_core_task(state_text)
        if state is InteractionState.COMPLETED:
            event(
                "evidence_verified",
                "completed",
                "The action completed and Nexuss recorded its evidence.",
            )
        elif state is InteractionState.AWAITING_APPROVAL:
            event(
                "approval_required",
                "awaiting_approval",
                (
                    "The exact protected action is waiting at the "
                    "approval boundary."
                ),
            )
        elif state is InteractionState.DENIED:
            event(
                "action_denied",
                "denied",
                "The active Nexuss policy denied the action.",
            )
        elif state is InteractionState.RESPONDED:
            event(
                "action_in_progress",
                "executing",
                (
                    "The governed Core task is active and remains observable "
                    "while execution continues."
                ),
            )
        else:
            event(
                "action_failed",
                "failed",
                "The action stopped in a controlled failure state.",
            )

        display = _task_display_text(
            task,
            fallback=classification.response,
        )
        user_message, assistant_message, conversation = (
            self._conversations.append_turn(
                conversation_id=request.conversation_id,
                user_text=sanitized.value,
                assistant_text=display,
                route=classification.route,
                provider_id=route_provider_id,
                model=route_model,
                pending_action=None,
                pending_capability_hint=None,
            )
        )
        response = InteractionResponse(
            interaction_id=interaction_id,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            kind=kind,
            state=state,
            display_text=display,
            resolved_instruction=instruction,
            capability_hint=classification.capability_hint,
            provider_id=route_provider_id,
            model=route_model,
            core_task_id=task.task_id,
            core_task_state=state_text,
            approval_required=(
                state is InteractionState.AWAITING_APPROVAL
            ),
            approval_id=approval,
            receipt_id=_receipt_id(receipt),
            evidence_count=_evidence_count(task),
            presentation=InteractionPresentation(
                task=task,
                receipt=receipt,
            ),
            conversation=conversation,
            user_message=user_message,
            assistant_message=assistant_message,
            events=tuple(events),
            created_at=now,
            updated_at=datetime.now(UTC),
        )
        self._interactions.save(response)
        return response

    def presentation(
        self,
        *,
        interaction_id: UUID,
        user_session_id: UUID,
    ) -> InteractionPresentation:
        stored = self._interactions.get(interaction_id)

        if stored is None or stored.core_task_id is None:
            raise UnifiedInteractionError(
                "INTERACTION_PRESENTATION_NOT_FOUND",
                "The governed task presentation was not found.",
            )

        if stored.conversation.user_session_id != user_session_id:
            raise UnifiedInteractionError(
                "INTERACTION_PRESENTATION_SESSION_MISMATCH",
                "The interaction belongs to another session.",
            )

        try:
            task = self._core.get_task(stored.core_task_id)
        except Exception as exc:
            raise UnifiedInteractionError(
                "INTERACTION_TASK_NOT_FOUND",
                "The governed Core task could not be reloaded.",
            ) from exc

        receipt = None
        try:
            receipt = self._core.get_receipt(stored.core_task_id)
        except Exception:
            receipt = None

        return InteractionPresentation(task=task, receipt=receipt)

    def save_conversation_as_note(
        self,
        *,
        conversation_id: UUID,
        request_id: UUID,
        user_session_id: UUID,
        note_title: str | None,
    ) -> SaveConversationResponse:
        conversation = self._conversations.get(conversation_id)

        if conversation is None:
            raise UnifiedInteractionError(
                "SESSION_JOURNAL_NOT_FOUND",
                "The conversation was not found.",
            )

        if conversation.user_session_id != user_session_id:
            raise UnifiedInteractionError(
                "SESSION_JOURNAL_SESSION_MISMATCH",
                "The conversation belongs to another session.",
            )

        messages = self._conversations.messages(
            conversation_id,
            limit=120,
        )
        markdown, digest = build_session_markdown(
            conversation,
            messages,
        )
        bounded_markdown = markdown[:14_000]
        title = (
            note_title.strip()
            if note_title and note_title.strip()
            else f"Nexuss Session — {conversation.title}"
        )
        instruction = (
            f"Create a note called {title} with the content: "
            f"{bounded_markdown}"
        )
        identity = IdentitySession(
            session_id=user_session_id,
            authenticated=True,
        )
        try:
            task = self._core.create_task(
                TaskRequest(
                    request_id=request_id,
                    channel=Channel.TEXT,
                    utterance=instruction,
                    user_session_id=user_session_id,
                    target_devices=[],
                    requested_at=datetime.now(UTC),
                    client_context={
                        "source": "conversation_journal_promotion",
                        "conversation_id": str(conversation_id),
                        "transcript_sha256": digest,
                        "automatic_memory_promotion": False,
                    },
                ),
                identity,
            )
        except Exception as exc:
            raise UnifiedInteractionError(
                "SESSION_NOTE_PREPARATION_FAILED",
                (
                    "Nexuss could not prepare the managed session "
                    "note. The local conversation remains saved."
                ),
            ) from exc

        state = _task_state(task)
        approval = _approval_id(task)
        receipt = None

        try:
            receipt = self._core.get_receipt(task.task_id)
        except Exception:
            receipt = None

        return SaveConversationResponse(
            conversation_id=conversation_id,
            note_title=title,
            transcript_sha256=digest,
            core_task_id=task.task_id,
            core_task_state=state,
            approval_required=(state == "awaiting_approval"),
            approval_id=approval,
            receipt_id=_receipt_id(receipt),
            presentation=InteractionPresentation(
                task=task,
                receipt=receipt,
            ),
            promoted_to_managed_note=(state == "completed"),
        )

"""DeepSeek-first chat/action classification without forced menus."""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import ValidationError

from nexuss.conversation.models import (
    ConversationRoute,
    RouteClassification,
)
from nexuss.engineering.models import ModelProposal
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.conversation.stabilization import (
    apply_truth_guard,
    constitutional_prompt_context,
    deterministic_route,
)

ProposalFunction = Callable[[ProviderRequest], ModelProposal]


class ConversationRoutingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConversationRouterService:
    """Classify once, answer chats, and clarify actions minimally."""

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        proposer: ProposalFunction,
    ) -> None:
        self._provider_id = provider_id
        self._model = model
        self._proposer = proposer

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    def route(
        self,
        *,
        user_text: str,
        conversation_context: str,
        pending_action: str | None,
        pending_capability_hint: str | None,
    ) -> RouteClassification:
        deterministic = deterministic_route(user_text)
        if deterministic is not None:
            return deterministic

        request = ProviderRequest(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(
                user_text=user_text,
                conversation_context=conversation_context,
                pending_action=pending_action,
                pending_capability_hint=(
                    pending_capability_hint
                ),
            ),
        )
        proposal = self._proposer(request)

        if proposal.tool_requests:
            raise ConversationRoutingError(
                "CONVERSATION_DIRECT_TOOL_REQUEST_DENIED",
                (
                    "The conversational provider attempted direct "
                    "tool transport."
                ),
            )

        if not proposal.done or not proposal.completion_message:
            raise ConversationRoutingError(
                "CONVERSATION_ROUTING_INCOMPLETE",
                "The provider did not return a completed route.",
            )

        try:
            raw = json.loads(proposal.completion_message)
        except json.JSONDecodeError as exc:
            raise ConversationRoutingError(
                "CONVERSATION_ROUTING_JSON_INVALID",
                "The provider route was not valid JSON.",
            ) from exc

        try:
            classification = RouteClassification.model_validate(raw)
        except ValidationError as exc:
            raise ConversationRoutingError(
                "CONVERSATION_ROUTING_SCHEMA_INVALID",
                "The provider route failed strict validation.",
            ) from exc

        self._validate_semantics(classification)
        return apply_truth_guard(user_text, classification)

    @staticmethod
    def _validate_semantics(
        classification: RouteClassification,
    ) -> None:
        if classification.route is ConversationRoute.CHAT:
            if (
                classification.action_instruction is not None
                or classification.clarification_question is not None
            ):
                raise ConversationRoutingError(
                    "CONVERSATION_CHAT_ROUTE_INVALID",
                    "Chat responses cannot include action fields.",
                )

        if classification.route is ConversationRoute.ACTION:
            if not classification.action_instruction:
                raise ConversationRoutingError(
                    "CONVERSATION_ACTION_INSTRUCTION_MISSING",
                    "Action routes require an exact instruction.",
                )
            if classification.clarification_question is not None:
                raise ConversationRoutingError(
                    "CONVERSATION_ACTION_ROUTE_INVALID",
                    "Ready actions cannot also request clarification.",
                )

        if classification.route is ConversationRoute.CLARIFICATION:
            if not classification.clarification_question:
                raise ConversationRoutingError(
                    "CONVERSATION_CLARIFICATION_MISSING",
                    (
                        "Clarification routes require one concise "
                        "question."
                    ),
                )
            if classification.action_instruction is not None:
                raise ConversationRoutingError(
                    "CONVERSATION_CLARIFICATION_ROUTE_INVALID",
                    (
                        "An unresolved action cannot include a ready "
                        "instruction."
                    ),
                )

    @staticmethod
    def _system_prompt() -> str:
        return (
            constitutional_prompt_context()
            + "\n\n"
            + "You are the conversational routing intelligence for "
            "Nexuss. Make the interface pass the Grandma Test. "
            "Classify the user's message into exactly one route: "
            "chat, action, or clarification.\n\n"
            "CHAT: greetings, ordinary questions, explanations, "
            "advice, brainstorming, writing, follow-up discussion, "
            "identity questions, and anything that does not require "
            "a Nexuss capability. Identity answers must use the supplied "
            "constitutional facts, never a generic or invented team. Reply "
            "directly and naturally. Never show a menu.\n\n"
            "ACTION: the user clearly asks Nexuss to inspect, check, "
            "list, launch, open, play, create, save, send, modify, "
            "build, test, research using live sources, or act through "
            "an account, repository, application, workspace, or "
            "device. Compound requests such as opening Chrome and searching "
            "for an explicit query are complete actions, not clarification. "
            "Return one exact natural-language instruction "
            "that the deterministic Nexuss action plane can execute. "
            "Do not claim execution.\n\n"
            "CLARIFICATION: use only when an action is clear but a "
            "necessary target or outcome is genuinely missing. Ask "
            "one short, specific question. Never present a multi-option "
            "menu. Do not clarify ordinary chat.\n\n"
            "If a pending action is supplied, treat the current message "
            "as the user's answer and resolve it into an action whenever "
            "possible.\n\n"
            "Return only valid JSON matching the Nexuss engineering "
            "provider transport exactly: "
            '{"summary":"conversation route",'
            '"tool_requests":[],'
            '"done":true,'
            '"completion_message":"ROUTE_JSON_STRING"}. '
            "The completion_message must be a JSON-encoded string. "
            "After decoding, it must match exactly: "
            '{"route":"chat|action|clarification",'
            '"response":"natural user-facing text",'
            '"action_instruction":null,'
            '"clarification_question":null,'
            '"capability_hint":null,'
            '"confidence":0.0}. '
            "Unknown fields are forbidden. Never include credentials, "
            "approval tokens, hidden reasoning, or claims that tools "
            "were executed. Do not guess a specific case, episode, person, "
            "title, current fact, or recent event. State uncertainty or route "
            "a live-source research action. Nexuss retains policy, approval, "
            "execution, verification, receipts, and final authority."
        )

    @staticmethod
    def _user_prompt(
        *,
        user_text: str,
        conversation_context: str,
        pending_action: str | None,
        pending_capability_hint: str | None,
    ) -> str:
        context = (
            conversation_context
            if conversation_context
            else "No earlier conversation."
        )
        pending = pending_action or "No pending action."
        hint = pending_capability_hint or "None"

        return (
            f"RECENT CONVERSATION:\n{context}\n\n"
            f"PENDING ACTION:\n{pending}\n"
            f"PENDING CAPABILITY HINT: {hint}\n\n"
            f"CURRENT USER MESSAGE:\n{user_text}\n\n"
            "Choose the simplest correct route. Normal conversation "
            "must receive a direct answer. Ask only one clarification "
            "when an executable action truly lacks its target."
        )

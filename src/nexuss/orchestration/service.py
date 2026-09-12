"""Provider-neutral, zero-execution action planning."""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexuss.ai.models import (
    AIProviderProfile,
    ProviderActionPlan,
    RequestedAction,
)
from nexuss.capabilities.broker import CapabilityBroker
from nexuss.capabilities.models import CapabilityMappingState
from nexuss.cognitive.models import CognitiveMode
from nexuss.engineering.models import ModelProposal
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.orchestration.models import ActionPlanEnvelope

ProposalFunction = Callable[[ProviderRequest], ModelProposal]


class ProviderPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(min_length=1, max_length=50_000)
    requested_actions: tuple[RequestedAction, ...] = ()


class UniversalActionPlanningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UniversalActionPlanningService:
    """Build and map an AI action plan without executing any action."""

    def __init__(
        self,
        *,
        provider: AIProviderProfile,
        model: str,
        proposer: ProposalFunction,
        broker: CapabilityBroker,
    ) -> None:
        self._provider = provider
        self._model = model.strip()
        self._proposer = proposer
        self._broker = broker
        if not self._model:
            raise ValueError("model must not be empty")

    def plan(
        self,
        *,
        instruction: str,
        mode: CognitiveMode,
    ) -> tuple[ActionPlanEnvelope, str]:
        normalized_instruction = instruction.strip()
        if not normalized_instruction:
            raise UniversalActionPlanningError(
                "AI_ORCHESTRATION_INSTRUCTION_EMPTY",
                "An orchestration instruction is required.",
            )
        if mode not in self._provider.supported_modes:
            raise UniversalActionPlanningError(
                "AI_ORCHESTRATION_MODE_UNSUPPORTED",
                (
                    f"{self._provider.display_name} does not support "
                    f"{mode.value!r}."
                ),
            )

        capability_catalog = self._broker.provider_catalog_summary()
        request = ProviderRequest(
            system_prompt=self._system_prompt(
                capability_catalog=capability_catalog,
            ),
            user_prompt=self._user_prompt(
                instruction=normalized_instruction,
                mode=mode,
            ),
        )
        proposal = self._proposer(request)

        if proposal.tool_requests:
            raise UniversalActionPlanningError(
                "AI_DIRECT_TOOL_REQUEST_DENIED",
                (
                    "The provider attempted to use the engineering tool "
                    "transport. Only requested Nexuss capabilities are valid."
                ),
            )
        if not proposal.done or not proposal.completion_message:
            raise UniversalActionPlanningError(
                "AI_ACTION_PLAN_INCOMPLETE",
                "The provider did not return a completed action plan.",
            )

        try:
            decoded = json.loads(proposal.completion_message)
        except json.JSONDecodeError as exc:
            raise UniversalActionPlanningError(
                "AI_ACTION_PLAN_JSON_INVALID",
                (
                    "The completion message was not the required strict "
                    "JSON action-plan payload."
                ),
            ) from exc

        try:
            payload = ProviderPlanPayload.model_validate(decoded)
        except ValidationError as exc:
            raise UniversalActionPlanningError(
                "AI_ACTION_PLAN_SCHEMA_INVALID",
                "The provider action plan failed schema validation.",
            ) from exc

        mapped = self._broker.map_actions(payload.requested_actions)
        counts = {
            CapabilityMappingState.VERIFIED_EXISTING: 0,
            CapabilityMappingState.SIMULATED: 0,
            CapabilityMappingState.PROHIBITED: 0,
            CapabilityMappingState.UNKNOWN: 0,
        }
        for item in mapped:
            counts[item.mapping_state] += 1

        plan = ProviderActionPlan(
            provider_id=self._provider.provider_id,
            model=self._model,
            mode=mode,
            summary=proposal.summary.strip(),
            response=payload.response,
            requested_actions=payload.requested_actions,
        )
        envelope = ActionPlanEnvelope(
            provider=self._provider,
            plan=plan,
            mapped_actions=mapped,
            action_count=len(mapped),
            verified_existing_count=counts[
                CapabilityMappingState.VERIFIED_EXISTING
            ],
            simulated_count=counts[
                CapabilityMappingState.SIMULATED
            ],
            prohibited_count=counts[
                CapabilityMappingState.PROHIBITED
            ],
            unknown_count=counts[
                CapabilityMappingState.UNKNOWN
            ],
            all_actions_mapped=(
                counts[CapabilityMappingState.PROHIBITED] == 0
                and counts[CapabilityMappingState.UNKNOWN] == 0
            ),
        )
        return envelope, capability_catalog

    def _system_prompt(self, *, capability_catalog: str) -> str:
        return (
            "You are an AI planning provider operating through the Nexuss "
            "Universal AI Orchestration Runtime. You may analyze the user "
            "instruction and REQUEST registered Nexuss capabilities. You do "
            "not execute tools, files, commands, accounts, applications, "
            "devices, approvals, or external writes. Nexuss maps every "
            "request, applies policy, obtains approval, executes, verifies, "
            "and issues receipts. Return only valid JSON matching the "
            "existing ModelProposal transport: "
            '{"summary":"concise plan summary","tool_requests":[],'
            '"done":true,"completion_message":"JSON_STRING"}. '
            "The completion_message string must decode to exactly: "
            '{"response":"user-facing explanation",'
            '"requested_actions":[{"action_key":"unique_key",'
            '"capability_id":"registered.id","arguments":{},'
            '"rationale":"why requested","expected_evidence":["item"],'
            '"depends_on":["earlier_key"]}]}. '
            "Use only capability IDs with provider_can_request=true. Never "
            "include credentials, secrets, tokens, cookies, approval tokens, "
            "raw shell commands, hidden reasoning, or claims of execution. "
            "Provider-visible capability catalogue follows:\n"
            f"{capability_catalog}"
        )

    @staticmethod
    def _user_prompt(
        *,
        instruction: str,
        mode: CognitiveMode,
    ) -> str:
        return (
            f"Planning mode: {mode.value}\n\n"
            f"User instruction:\n{instruction}\n\n"
            "Prepare the smallest reliable action plan. Request no "
            "unnecessary action. This gate executes nothing."
        )

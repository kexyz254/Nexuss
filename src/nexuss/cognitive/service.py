"""Proposal-only cognitive orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable

from nexuss.cognitive.models import CognitiveMode, CognitiveProposal
from nexuss.engineering.models import ModelProposal
from nexuss.engineering.providers.base import ProviderRequest

ProposalFunction = Callable[[ProviderRequest], ModelProposal]

_STEP_PATTERN = re.compile(
    r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$"
)


class CognitiveProposalError(RuntimeError):
    """Raised when a provider violates the cognitive contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CognitiveProposalService:
    """Use an external model for proposals without granting authority."""

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        proposer: ProposalFunction,
    ) -> None:
        normalized_provider = provider_id.strip()
        normalized_model = model.strip()

        if not normalized_provider:
            raise ValueError("provider_id must not be empty")

        if not normalized_model:
            raise ValueError("model must not be empty")

        self._provider_id = normalized_provider
        self._model = normalized_model
        self._proposer = proposer

    def propose(
        self,
        *,
        instruction: str,
        mode: CognitiveMode,
        context_summary: str = "",
    ) -> CognitiveProposal:
        normalized_instruction = instruction.strip()
        normalized_context = context_summary.strip()

        if not normalized_instruction:
            raise CognitiveProposalError(
                "COGNITIVE_INSTRUCTION_EMPTY",
                "A cognitive instruction is required.",
            )

        request = ProviderRequest(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(
                instruction=normalized_instruction,
                mode=mode,
                context_summary=normalized_context,
            ),
        )

        proposal = self._proposer(request)

        if proposal.tool_requests:
            raise CognitiveProposalError(
                "COGNITIVE_TOOL_REQUEST_DENIED",
                (
                    "The cognitive provider attempted to request "
                    "tool authority."
                ),
            )

        if not proposal.done or not proposal.completion_message:
            raise CognitiveProposalError(
                "COGNITIVE_PROPOSAL_INCOMPLETE",
                (
                    "The cognitive provider did not return a "
                    "completed proposal."
                ),
            )

        response = proposal.completion_message.strip()

        if not response:
            raise CognitiveProposalError(
                "COGNITIVE_RESPONSE_EMPTY",
                "The cognitive provider returned an empty response.",
            )

        return CognitiveProposal(
            provider_id=self._provider_id,
            model=self._model,
            mode=mode,
            summary=proposal.summary.strip(),
            response=response,
            steps=self._extract_steps(response),
            requested_capabilities=(),
            requires_execution=False,
            requires_approval=False,
            provider_generated_proposal_only=True,
            nexuss_retains_final_authority=True,
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are the proposal-only cognitive provider for Nexuss. "
            "You may reason, analyze, write, design, review, debug, and "
            "produce code or implementation proposals. You have no tool, "
            "shell, file, network, device, approval, credential, publishing, "
            "or execution authority. Never claim that you performed an "
            "action. Return only valid JSON matching this exact contract: "
            '{"summary":"concise summary","tool_requests":[],'
            '"done":true,"completion_message":"complete user-facing answer"}. '
            "Do not return hidden reasoning, reasoning_content, chain of "
            "thought, credentials, approval tokens, or tool requests. "
            "Nexuss retains policy, approval, execution, verification, "
            "receipt, audit, and final authority."
        )

    @staticmethod
    def _user_prompt(
        *,
        instruction: str,
        mode: CognitiveMode,
        context_summary: str,
    ) -> str:
        context = (
            context_summary
            if context_summary
            else "No additional private context was supplied."
        )

        return (
            f"Cognitive mode: {mode.value}\n\n"
            f"User instruction:\n{instruction}\n\n"
            f"Privacy-filtered context:\n{context}\n\n"
            "Produce a professional proposal or answer only. "
            "Do not request tools or claim execution."
        )

    @staticmethod
    def _extract_steps(response: str) -> tuple[str, ...]:
        steps: list[str] = []

        for line in response.splitlines():
            match = _STEP_PATTERN.match(line)

            if not match:
                continue

            step = match.group(1).strip()

            if step and step not in steps:
                steps.append(step)

        return tuple(steps[:25])

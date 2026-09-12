"""Tests for the proposal-only cognitive control plane."""

from __future__ import annotations

import pytest

from nexuss.cognitive.models import CognitiveMode
from nexuss.cognitive.service import (
    CognitiveProposalError,
    CognitiveProposalService,
)
from nexuss.engineering.models import ModelProposal


def test_valid_proposal_preserves_nexuss_authority() -> None:
    def proposer(_request):
        return ModelProposal(
            summary="A bounded architecture proposal.",
            tool_requests=(),
            done=True,
            completion_message=(
                "1. Define read-only metrics.\n"
                "2. Add a verified dashboard view.\n"
                "3. Preserve policy and receipt boundaries."
            ),
        )

    service = CognitiveProposalService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer,
    )

    result = service.propose(
        instruction="Design a read-only dashboard.",
        mode=CognitiveMode.DESIGN,
    )

    assert result.provider_id == "deepseek"
    assert result.model == "deepseek-v4-pro"
    assert result.requires_execution is False
    assert result.requires_approval is False
    assert result.requested_capabilities == ()
    assert result.provider_generated_proposal_only is True
    assert result.nexuss_retains_final_authority is True
    assert result.steps == (
        "Define read-only metrics.",
        "Add a verified dashboard view.",
        "Preserve policy and receipt boundaries.",
    )


def test_tool_request_is_denied() -> None:
    def proposer(_request):
        return ModelProposal.model_construct(
            summary="Attempted tool request.",
            tool_requests=(object(),),
            done=True,
            completion_message="The proposal attempted execution.",
        )

    service = CognitiveProposalService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer,
    )

    with pytest.raises(
        CognitiveProposalError,
        match="tool authority",
    ) as error:
        service.propose(
            instruction="Modify the repository.",
            mode=CognitiveMode.CODE,
        )

    assert error.value.code == "COGNITIVE_TOOL_REQUEST_DENIED"


def test_incomplete_provider_response_is_denied() -> None:
    def proposer(_request):
        return ModelProposal(
            summary="Incomplete proposal.",
            tool_requests=(),
            done=False,
            completion_message=None,
        )

    service = CognitiveProposalService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer,
    )

    with pytest.raises(CognitiveProposalError) as error:
        service.propose(
            instruction="Analyze this architecture.",
            mode=CognitiveMode.ANALYZE,
        )

    assert error.value.code == "COGNITIVE_PROPOSAL_INCOMPLETE"

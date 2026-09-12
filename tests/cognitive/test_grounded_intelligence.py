"""Tests for grounded cognitive intelligence and receipts."""

from __future__ import annotations

from uuid import uuid4

from nexuss.cognitive.context import build_cognitive_context
from nexuss.cognitive.models import CognitiveMode, CognitiveProposal
from nexuss.cognitive.receipt import build_cognitive_receipt


def test_context_is_bounded_and_contains_no_sensitive_material() -> None:
    context = build_cognitive_context(provider_status="ready")
    serialized = context.to_provider_summary().lower()

    assert context.contains_credentials is False
    assert context.contains_file_contents is False
    assert context.contains_approval_tokens is False
    assert context.contains_hidden_reasoning is False
    assert '"api_key":' not in serialized
    assert '"approval_token":' not in serialized
    assert '"reasoning_content":' not in serialized
    assert len(serialized) < 50_000


def test_receipt_discloses_external_processing_without_authority() -> None:
    proposal = CognitiveProposal(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        mode=CognitiveMode.DESIGN,
        summary="Grounded design proposal.",
        response="1. Add a bounded operational status view.",
    )

    receipt = build_cognitive_receipt(
        request_id=uuid4(),
        instruction="Design a Nexuss dashboard.",
        context_summary='{"active_mode":"test"}',
        proposal=proposal,
    )

    assert receipt.provider_invoked is True
    assert receipt.proposal_validated is True
    assert receipt.external_processing_used is True
    assert receipt.execution_authorized is False
    assert receipt.tool_capabilities_executed == 0
    assert receipt.approval_requested is False
    assert receipt.files_modified is False
    assert receipt.external_writes is False
    assert receipt.hidden_reasoning_stored is False
    assert receipt.nexuss_retains_final_authority is True
    assert len(receipt.events) == 4

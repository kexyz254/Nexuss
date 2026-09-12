"""Verified non-write receipts for cognitive proposals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from nexuss.cognitive.models import CognitiveProposal


class CognitiveLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    state: str
    event_type: str
    occurred_at: datetime
    detail: str


class CognitiveReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID
    receipt_type: Literal["cognitive_proposal"]
    request_id: UUID
    provider_id: str
    model: str
    mode: str

    request_sha256: str
    context_sha256: str
    response_sha256: str

    provider_invoked: Literal[True] = True
    proposal_validated: Literal[True] = True
    external_processing_used: Literal[True] = True

    execution_authorized: Literal[False] = False
    tool_capabilities_executed: int = 0
    approval_requested: Literal[False] = False
    files_modified: Literal[False] = False
    external_writes: Literal[False] = False
    hidden_reasoning_stored: Literal[False] = False
    nexuss_retains_final_authority: Literal[True] = True

    events: tuple[CognitiveLifecycleEvent, ...]
    created_at: datetime


class CognitiveProposalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: CognitiveProposal
    receipt: CognitiveReceipt


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_cognitive_receipt(
    *,
    request_id: UUID,
    instruction: str,
    context_summary: str,
    proposal: CognitiveProposal,
) -> CognitiveReceipt:
    created_at = datetime.now(UTC)
    request_hash = _sha256(instruction)
    context_hash = _sha256(context_summary)
    response_hash = _sha256(proposal.response)

    receipt_id = uuid5(
        NAMESPACE_URL,
        (
            "nexuss:cognitive-receipt:"
            f"{request_id}:{response_hash}"
        ),
    )

    events = (
        CognitiveLifecycleEvent(
            sequence=1,
            state="received",
            event_type="cognitive_request_received",
            occurred_at=created_at,
            detail=(
                "Authenticated cognitive request accepted with explicit "
                "external provider selection."
            ),
        ),
        CognitiveLifecycleEvent(
            sequence=2,
            state="planned",
            event_type="cognitive_policy_applied",
            occurred_at=created_at,
            detail=(
                "Proposal-only policy applied. Tools, writes, approvals, "
                "and execution authority were excluded."
            ),
        ),
        CognitiveLifecycleEvent(
            sequence=3,
            state="verifying",
            event_type="provider_proposal_received",
            occurred_at=created_at,
            detail=(
                "DeepSeek returned structured output for schema and "
                "authority-boundary verification."
            ),
        ),
        CognitiveLifecycleEvent(
            sequence=4,
            state="completed",
            event_type="cognitive_proposal_verified",
            occurred_at=created_at,
            detail=(
                "The proposal passed validation and a non-write cognitive "
                "receipt was generated."
            ),
        ),
    )

    return CognitiveReceipt(
        receipt_id=receipt_id,
        receipt_type="cognitive_proposal",
        request_id=request_id,
        provider_id=proposal.provider_id,
        model=proposal.model,
        mode=proposal.mode.value,
        request_sha256=request_hash,
        context_sha256=context_hash,
        response_sha256=response_hash,
        events=events,
        created_at=created_at,
    )

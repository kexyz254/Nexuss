"""Reusable proposal-only cognitive runtime for Nexuss Core and API surfaces."""

from __future__ import annotations

from uuid import UUID

from nexuss.cognitive.context import build_cognitive_context
from nexuss.cognitive.models import CognitiveMode
from nexuss.cognitive.receipt import (
    CognitiveProposalEnvelope,
    build_cognitive_receipt,
)
from nexuss.cognitive.service import CognitiveProposalService
from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.models import (
    EngineeringTaskSpec,
    TaskSensitivity,
    WorkspaceKind,
)
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)


def create_cognitive_proposal(
    *,
    request_id: UUID,
    instruction: str,
    mode: CognitiveMode,
) -> CognitiveProposalEnvelope:
    """Generate one proposal with zero tool or execution authority."""

    connections = EngineeringProviderConnectionService(
        DpapiSecretVault(),
        timeout_seconds=120.0,
    )
    access = connections.deepseek_access()
    if not access.available:
        from nexuss.engineering.errors import EngineeringError

        raise EngineeringError(
            "COGNITIVE_PROVIDER_UNAVAILABLE",
            access.user_message,
            retryable=False,
        )

    router = connections.build_deepseek_router()
    profile = router.profile("deepseek")
    context = build_cognitive_context(
        provider_status=access.code.value,
    )
    context_summary = context.to_provider_summary()

    task = EngineeringTaskSpec(
        task_id=request_id,
        goal=instruction,
        provider_id="deepseek",
        workspace_kind=WorkspaceKind.LOCAL,
        sensitivity=TaskSensitivity.PRIVATE,
        external_processing_approved=True,
        allowed_tools=(),
        max_rounds=1,
        max_files_changed=1,
        max_runtime_seconds=120,
    )
    cognitive = CognitiveProposalService(
        provider_id="deepseek",
        model=profile.model,
        proposer=lambda request: router.propose(task, request),
    )
    proposal = cognitive.propose(
        instruction=instruction,
        mode=mode,
        context_summary=context_summary,
    )
    receipt = build_cognitive_receipt(
        request_id=request_id,
        instruction=instruction,
        context_summary=context_summary,
        proposal=proposal,
    )
    return CognitiveProposalEnvelope(
        proposal=proposal,
        receipt=receipt,
    )

"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Explicit capability registry for the Nexuss P3 approved-action platform.
"""

from nexuss.domain.models import (
    ApprovalPolicy,
    CapabilityManifest,
    CapabilityStatus,
    RiskTier,
)

_MANIFESTS = (
    CapabilityManifest(
        capability_id="assistant.respond",
        version="1.0.0",
        title="Nexuss conversation",
        description="Answer identity, help, and capability questions without side effects.",
        risk_tier=RiskTier.INFORMATIONAL,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="deterministic_local",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="workspace.read_status",
        version="1.0.0",
        title="Workspace status",
        description="Read bounded local repository and runtime metadata.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="workspace.create_note",
        version="1.0.0",
        title="Create managed note",
        description="Create a verified Markdown note in the Nexuss managed workspace.",
        risk_tier=RiskTier.MEDIUM,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=True,
        execution_mode="live_local_controlled_write",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="workspace.rollback_create_note",
        version="1.0.0",
        title="Undo note creation",
        description="Remove only the unchanged note created by the associated receipt.",
        risk_tier=RiskTier.MEDIUM,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="live_local_receipt_bound_rollback",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="calendar.read_summary",
        version="0.1.0",
        title="Calendar summary",
        description="P1 deterministic simulation only.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
    CapabilityManifest(
        capability_id="email.read_summary",
        version="0.1.0",
        title="Email summary",
        description="P1 deterministic simulation only.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
    CapabilityManifest(
        capability_id="github.read_summary",
        version="0.1.0",
        title="GitHub summary",
        description="P1 deterministic simulation only.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
    CapabilityManifest(
        capability_id="ats.read_health",
        version="0.1.0",
        title="ATS health",
        description="Protected read-only simulation; no live ATS connection.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
    CapabilityManifest(
        capability_id="ats.read_intelligence",
        version="0.1.0",
        title="ATS intelligence",
        description="Protected read-only simulation; no live market data.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
)

_BY_ID = {manifest.capability_id: manifest for manifest in _MANIFESTS}


def list_capabilities() -> tuple[CapabilityManifest, ...]:
    return _MANIFESTS


def get_capability(capability_id: str) -> CapabilityManifest | None:
    return _BY_ID.get(capability_id)

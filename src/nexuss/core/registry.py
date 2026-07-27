"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Explicit capability registry for the Nexuss P5 knowledge, media, and mobile action plane.
"""

from nexuss.domain.models import (
    ApprovalChannel,
    ApprovalPolicy,
    CapabilityManifest,
    CapabilityStatus,
    RiskTier,
)

_MANIFESTS = (
    CapabilityManifest(
        capability_id="device.pair_phone",
        version="1.0.0",
        title="Pair a phone",
        description=(
            "Issue a single-use pairing challenge for a trusted phone. "
            "Trust transfers only when the code is entered on the handset."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=True,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="device.list_phones",
        version="1.0.0",
        title="List paired phones",
        description="Read the paired-device inventory without exposing token digests.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="device.unpair_phone",
        version="1.0.0",
        title="Unpair a phone",
        description=(
            "Revoke a paired phone permanently. Approved on the desktop, never "
            "on the phone: a handset you have lost cannot authorise its own removal."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="live_local_controlled_write",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
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
        capability_id="device.launch_notepad",
        version="1.0.0",
        title="Launch Notepad on trusted Windows node",
        description=(
            "Launch only the fixed Windows Notepad executable through a signed, "
            "loopback-only device-node command envelope."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=True,
        execution_mode="trusted_device_node",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.PHONE,
    ),
    CapabilityManifest(
        capability_id="device.rollback_launch_notepad",
        version="1.0.0",
        title="Close receipt-bound Notepad process",
        description=(
            "Terminate only the process created by the associated signed device command."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="trusted_device_node_rollback",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.PHONE,
    ),
    CapabilityManifest(
        capability_id="knowledge.web_research",
        version="1.0.0",
        title="Public web research",
        description="Retrieve bounded public reference sources and prepare a cited brief.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_public_web_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="media.youtube.discover",
        version="1.0.0",
        title="YouTube discovery",
        description="Search through the official YouTube Data API or return a safe handoff state.",
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="official_media_connector",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="phone.open_youtube",
        version="1.1.0",
        title="Open YouTube on paired phone",
        description=(
            "Dispatch only an allowlisted HTTPS YouTube search to the paired phone "
            "from an authenticated user request."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="paired_phone_direct_youtube_handoff",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="device.open_web_search",
        version="1.0.0",
        title="Open approved web search",
        description="Open an allowlisted HTTPS search URL in Chrome on the trusted Windows node.",
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="trusted_device_browser_handoff",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.PHONE,
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

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
        capability_id="memory.remember",
        version="1.0.0",
        title="Remember",
        description=(
            "Store a user-asserted statement in durable memory with full "
            "provenance. Credential-shaped content is refused, not masked."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=True,
        execution_mode="live_local_controlled_write",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="memory.recall",
        version="1.0.0",
        title="Recall",
        description=(
            "Search durable memory. Results always carry source, trust tier "
            "and decayed confidence; provenance is never stripped."
        ),
        risk_tier=RiskTier.INFORMATIONAL,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="memory.forget",
        version="1.0.0",
        title="Forget a topic",
        description=(
            "Delete every claim on a topic permanently. Desktop approval is "
            "required because deletion is irreversible."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="live_local_controlled_write",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
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
        capability_id="assistant.converse",
        version="1.0.0",
        title="Converse",
        description=(
            "Answer greetings, courtesies and clock questions deterministically. "
            "No external source is consulted and nothing is written."
        ),
        risk_tier=RiskTier.INFORMATIONAL,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="knowledge.answer",
        version="1.0.0",
        title="Answer a question",
        description=(
            "Answer an open question from memory when memory is confident, "
            "and from cited public sources when it is not. The answer always "
            "states which of the two it used."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_public_web_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="assistant.respond",
        version="1.1.0",
        title="Nexuss constitutional conversation",
        description=(
            "Answer identity, governance, help, and capability questions "
            "through verified local constitutional or deterministic evidence."
        ),
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
        capability_id="engineering.repair_failed_build",
        version="1.0.0",
        title="Repair latest failed engineering build",
        description=(
            "Resume the newest retained failed Prompt-to-Build candidate from its "
            "local diagnostic evidence, permit at most one targeted provider repair "
            "proposal, re-run deterministic verification, and apply only if clean."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="isolated_engineering_repair",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
    CapabilityManifest(
        capability_id="engineering.verify_acceptance",
        version="1.0.0",
        title="Verify engineering acceptance",
        description=(
            "Collect deterministic local acceptance evidence for an installed "
            "engineering phase without invoking a paid model or modifying source."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="deterministic_local_readonly",
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
        capability_id="mobile.signals.ingest",
        version="1.0.0",
        title="Trusted mobile communication ingress",
        description=(
            "Accept allowlisted notification and user-shared communication signals "
            "from an authenticated paired Android companion using HMAC request assertions."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="trusted_mobile_ingress",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="mobile.signals.read",
        version="1.0.0",
        title="Mobile communication feed",
        description=(
            "Read the normalized phone, SMS, WhatsApp, Instagram, and Facebook Lite "
            "signal feed without modifying any application or external account."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_local_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="mobile.action.prepare",
        version="1.0.0",
        title="Prepare exact mobile application action",
        description=(
            "Create a device-bound action proposal with an exact preview, payload hash, "
            "short expiry, and no execution before approval."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=True,
        execution_mode="local_action_preparation",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="mobile.action.execute",
        version="1.0.0",
        title="Execute approved mobile application handoff",
        description=(
            "On a paired Android companion, execute only dialer handoff, SMS composition, "
            "app-provided notification reply, or conversation opening after exact on-device "
            "biometric approval and return execution evidence."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="trusted_mobile_companion",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.PHONE,
    ),
    CapabilityManifest(
        capability_id="google.workspace.connection",
        version="1.0.0",
        title="Encrypted Google Workspace connection",
        description=(
            "Connect one Google identity through desktop OAuth with PKCE "
            "and Windows user-scoped DPAPI storage."
        ),
        risk_tier=RiskTier.MEDIUM,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=True,
        execution_mode="desktop_oauth_pkce",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
    CapabilityManifest(
        capability_id="google.gmail.read",
        version="1.0.0",
        title="Gmail read intelligence",
        description=(
            "Read bounded Gmail messages through the official Gmail API "
            "using only the gmail.readonly scope."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="official_google_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="google.calendar.read",
        version="1.0.0",
        title="Calendar read intelligence",
        description=(
            "Read calendar inventory and bounded event windows through "
            "official Google Calendar read-only scopes."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="official_google_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="google.contacts.read",
        version="1.0.0",
        title="Google Contacts resolution",
        description=(
            "Resolve bounded contact names, email addresses, phone numbers, "
            "and organizations through the People API read-only scope."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="official_google_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="commitments.prepare_day",
        version="1.0.0",
        title="Prepare unified operational day",
        description=(
            "Correlate Gmail, Calendar, Contacts, and trusted-mobile signals "
            "into evidence-backed commitments and schedule proposals."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="cross_channel_readonly_intelligence",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="communications.external_write",
        version="0.1.0",
        title="External communication and calendar writes",
        description=(
            "Sending Gmail, modifying Calendar, and changing Contacts remain "
            "disabled until approval-bound execution is verified."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.PROHIBITED,
        reversible=False,
        execution_mode="not_enabled",
        status=CapabilityStatus.PROHIBITED,
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
        description=(
            "Legacy deterministic simulation retained for "
            "daily briefing compatibility."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="simulated",
        status=CapabilityStatus.SIMULATED,
    ),
    CapabilityManifest(
        capability_id="engineering.build_artifact",
        version="1.0.0",
        title="Developer Prompt-to-Build",
        description=(
            "Use the connected DeepSeek engineering provider to modify an isolated "
            "copy of Nexuss, run baseline-aware regression validation, package the "
            "result, and optionally apply only a regression-clean build to live source."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="isolated_engineering_self_build",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
    CapabilityManifest(
        capability_id="github.connection.status",
        version="1.0.0",
        title="GitHub connection status",
        description=(
            "Verify the encrypted GitHub connector identity without "
            "exposing credentials."
        ),
        risk_tier=RiskTier.INFORMATIONAL,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_github_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="github.repositories.list",
        version="1.0.0",
        title="GitHub repository inventory",
        description=(
            "Read bounded repository metadata for the verified GitHub account."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="live_github_readonly",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="github.repository.create",
        version="1.0.0",
        title="Create private GitHub repository",
        description=(
            "Create one exact private, uninitialized repository after "
            "payload-bound phone approval and independent verification."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=False,
        execution_mode="live_github_controlled_write",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.PHONE,
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


# P6.13 APPROVED DEVELOPMENT PACKAGE CAPABILITIES
_MANIFESTS = (
    *_MANIFESTS,
    CapabilityManifest(
        capability_id="engineering.package.inspect",
        version="1.0.0",
        title="Inspect Nexuss development package",
        description=(
            "Quarantine a reviewed Nexuss development ZIP and verify its manifest, "
            "payload hashes, target preconditions, and secret-free intake without "
            "using an LLM or modifying the live repository."
        ),
        risk_tier=RiskTier.LOW,
        approval_policy=ApprovalPolicy.NONE,
        reversible=False,
        execution_mode="local_secure_development_package_inspection",
        status=CapabilityStatus.ACTIVE,
    ),
    CapabilityManifest(
        capability_id="engineering.package.apply",
        version="1.0.0",
        title="Apply approved Nexuss development package",
        description=(
            "After exact desktop approval, validate a reviewed development ZIP in an "
            "isolated repository copy, require baseline-equivalent regression results, "
            "create a rollback backup, and atomically apply the verified payload."
        ),
        risk_tier=RiskTier.HIGH,
        approval_policy=ApprovalPolicy.EXPLICIT,
        reversible=True,
        execution_mode="local_baseline_aware_development_package_apply",
        status=CapabilityStatus.ACTIVE,
        approval_channel=ApprovalChannel.DESKTOP,
    ),
)

_BY_ID = {manifest.capability_id: manifest for manifest in _MANIFESTS}


def list_capabilities() -> tuple[CapabilityManifest, ...]:
    return _MANIFESTS


def get_capability(capability_id: str) -> CapabilityManifest | None:
    return _BY_ID.get(capability_id)

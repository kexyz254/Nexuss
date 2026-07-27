"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Capability execution router for verified local, public-web, media, and device actions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from nexuss.constitution import ConstitutionError, get_constitution
from nexuss.core.local_workspace import (
    LocalWorkspaceEvidenceError,
    collect_local_workspace_status,
)
from nexuss.core.managed_notes import ManagedNoteStore, PreparedNote
from nexuss.core.simulator import execute_step as execute_simulated_step
from nexuss.core.web_actions import (
    WebActionValidationError,
    validate_youtube_handoff_url,
)
from nexuss.device.client import DeviceCommandError, DeviceNodeClient
from nexuss.domain.models import (
    CapabilityResult,
    EvidenceRecord,
    PlanStep,
    StepStatus,
)
from nexuss.knowledge.provider import KnowledgeProvider, KnowledgeProviderError
from nexuss.media.youtube import MediaProviderError, YouTubeProvider
from nexuss.memory.models import SourceTrust, Volatility
from nexuss.memory.store import MemoryStore, MemoryWriteRefused
from nexuss.mobile.models import MobilePairedDevice, MobilePairingChallenge


class PhonePairingGateway(Protocol):
    """The slice of the mobile gateway the executor depends on.

    Declared as a port so the executor does not import the concrete gateway
    and the tests can drive it with a stub.
    """

    def create_pairing(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> MobilePairingChallenge: ...

    def list_devices(self) -> tuple[MobilePairedDevice, ...]: ...

    def revoke(self, device_id: UUID) -> None: ...


def _failed(step: PlanStep, error_code: str) -> CapabilityResult:
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.FAILED,
        evidence=[],
        error_code=error_code,
    )


def _execute_assistant_response(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    response_key = str(
        step.parameters.get("response_key", "")
    ).strip()

    if response_key:
        try:
            constitution = get_constitution()
            response = constitution.standard_response(response_key)
        except ConstitutionError:
            return _failed(step, "CONSTITUTION_UNAVAILABLE")

        rule_by_response = {
            "who_are_you": (
                "Nexuss identity is defined by the active Constitution."
            ),
            "who_is_your_founder": (
                "Founder identity is a constitutional system fact."
            ),
            "who_developed_you": (
                "Original developer identity is constitutionally defined."
            ),
            "who_is_your_boss": (
                "Operational authority requires authenticated roles."
            ),
            "user_claims_to_be_peter": (
                "Conversational identity claims do not grant authority."
            ),
            "ignore_constitution": (
                "Ordinary conversation cannot amend or disable "
                "the Constitution."
            ),
        }

        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="nexuss:constitution",
                    observed_at=timestamp,
                    attributes={
                        "response": response,
                        "response_key": response_key,
                        "source_mode": (
                            "constitutional_local_verified"
                        ),
                        "authority_source": (
                            "nexuss_constitution"
                        ),
                        "constitution_status": "active",
                        "constitution_version": (
                            constitution.version
                        ),
                        "constitution_sha256": (
                            constitution.sha256
                        ),
                        "integrity_verified": True,
                        "grants_authority": False,
                        "rule_applied": rule_by_response.get(
                            response_key,
                            "The active Constitution governs "
                            "this response.",
                        ),
                    },
                )
            ],
        )

    response = str(step.parameters.get("response", "")).strip()
    if not response:
        return _failed(step, "ASSISTANT_RESPONSE_MISSING")

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="nexuss:deterministic_response",
                observed_at=timestamp,
                attributes={
                    "response": response,
                    "source_mode": "deterministic_local",
                    "authority_source": (
                        "registered_assistant_capability"
                    ),
                },
            )
        ],
    )


def _execute_create_note(
    step: PlanStep,
    timestamp: datetime,
    note_store: ManagedNoteStore,
) -> CapabilityResult:
    content = str(step.parameters["content"])
    prepared = PreparedNote(
        title=str(step.parameters["title"]),
        filename=str(step.parameters["filename"]),
        content=content,
        content_bytes=content.encode("utf-8"),
        content_sha256=str(step.parameters["content_sha256"]),
    )
    created = note_store.create(prepared)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:managed_workspace",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_controlled_write",
                    "filename": created.filename,
                    "managed_path": str(created.path),
                    "byte_count": created.byte_count,
                    "sha256": created.sha256,
                    "verified": True,
                    "reversible": True,
                },
            )
        ],
    )


def _execute_launch_notepad(
    step: PlanStep,
    timestamp: datetime,
    task_id: UUID,
    device_client: DeviceNodeClient,
) -> CapabilityResult:
    target_node_id = str(
        step.parameters.get("target_node_id", "windows-primary")
    )
    try:
        evidence = device_client.launch_notepad(task_id, target_node_id)
    except DeviceCommandError:
        return _failed(step, "TRUSTED_DEVICE_COMMAND_FAILED")
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=(
            StepStatus.VERIFIED
            if evidence.verified_running
            else StepStatus.FAILED
        ),
        evidence=[
            EvidenceRecord(
                source="device:windows-node",
                observed_at=timestamp,
                attributes={
                    "source_mode": evidence.source_mode,
                    "command_id": str(evidence.command_id),
                    "node_id": evidence.node_id,
                    "node_hostname": evidence.node_hostname,
                    "executable": evidence.executable,
                    "process_id": evidence.process_id,
                    "started_at": evidence.started_at.isoformat(),
                    "verified_running": evidence.verified_running,
                    "reversible": True,
                },
            )
        ],
        error_code=(
            None
            if evidence.verified_running
            else "DEVICE_PROCESS_NOT_RUNNING"
        ),
    )


def _execute_web_research(
    step: PlanStep,
    timestamp: datetime,
    provider: KnowledgeProvider,
) -> CapabilityResult:
    try:
        attributes = provider.research(
            str(step.parameters.get("query", ""))
        )
    except KnowledgeProviderError as exc:
        return _failed(step, str(exc))
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="web:wikipedia",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )


def _execute_youtube_discovery(
    step: PlanStep,
    timestamp: datetime,
    provider: YouTubeProvider,
) -> CapabilityResult:
    try:
        attributes = provider.discover(
            str(step.parameters.get("query", ""))
        )
    except MediaProviderError as exc:
        return _failed(step, str(exc))
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="media:youtube",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )


def _execute_phone_handoff(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    try:
        launch_url = validate_youtube_handoff_url(
            str(step.parameters.get("launch_url", ""))
        )
    except WebActionValidationError:
        return _failed(step, "PHONE_YOUTUBE_URL_NOT_ALLOWLISTED")

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="mobile:paired_phone",
                observed_at=timestamp,
                attributes={
                    "source_mode": "paired_phone_direct_youtube_handoff",
                    "launch_url": launch_url,
                    "query": str(step.parameters.get("query", "")),
                    "handoff_authorized": True,
                    "delivery_state": "queued_for_paired_phone",
                    "app_open_verified": False,
                },
            )
        ],
    )


def _execute_web_search(
    step: PlanStep,
    timestamp: datetime,
    task_id: UUID,
    device_client: DeviceNodeClient,
) -> CapabilityResult:
    try:
        evidence = device_client.open_web_search(
            task_id,
            str(
                step.parameters.get(
                    "target_node_id",
                    "windows-primary",
                )
            ),
            str(step.parameters.get("launch_url", "")),
        )
    except DeviceCommandError:
        return _failed(step, "TRUSTED_BROWSER_HANDOFF_FAILED")
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="device:windows-node",
                observed_at=timestamp,
                attributes={
                    "source_mode": (
                        "live_trusted_device_browser_handoff"
                    ),
                    "node_id": evidence.node_id,
                    "executable": evidence.executable,
                    "process_id": evidence.process_id,
                    "launch_url": str(
                        step.parameters.get("launch_url", "")
                    ),
                    "verified_handoff": evidence.verified_running,
                    "reversible": False,
                },
            )
        ],
    )


def _execute_pair_phone(
    step: PlanStep,
    timestamp: datetime,
    session_id: UUID,
    gateway: PhonePairingGateway,
) -> CapabilityResult:
    """Issue a pairing challenge.

    Issuing a code grants nothing on its own. Trust transfers only when the
    code is entered on the handset, inside the ten-minute window, against a
    rate-limited endpoint that is reachable on loopback only.
    """
    challenge = gateway.create_pairing(session_id, now=timestamp)
    separator = "&" if "?" in challenge.mobile_url else "?"
    pair_url = f"{challenge.mobile_url}{separator}pair={challenge.pairing_code}"

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:mobile_pairing_gateway",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_readonly",
                    "pairing_code": challenge.pairing_code,
                    "mobile_url": challenge.mobile_url,
                    "pair_url": pair_url,
                    "expires_at": challenge.expires_at.isoformat(),
                },
            )
        ],
    )


def _execute_list_phones(
    step: PlanStep,
    timestamp: datetime,
    gateway: PhonePairingGateway,
) -> CapabilityResult:
    devices = gateway.list_devices()
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:mobile_pairing_gateway",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_readonly",
                    "device_count": len(devices),
                    "devices": [
                        {
                            "device_id": str(device.device_id),
                            "device_label": device.device_label,
                            "paired_at": device.paired_at.isoformat(),
                            "last_seen_at": device.last_seen_at.isoformat(),
                            "expires_at": device.expires_at.isoformat(),
                        }
                        for device in devices
                    ],
                },
            )
        ],
    )


def _execute_unpair_phone(
    step: PlanStep,
    timestamp: datetime,
    gateway: PhonePairingGateway,
) -> CapabilityResult:
    """Revoke one paired phone.

    Refuses rather than guessing when the target is ambiguous. Revocation is
    irreversible, so picking a device on the operator's behalf is not an
    acceptable failure mode.
    """
    requested = str(step.parameters.get("device_label", "")).strip()
    devices = gateway.list_devices()

    if not devices:
        return _failed(step, "NO_PAIRED_DEVICE")

    if requested:
        matches = [
            device
            for device in devices
            if device.device_label.casefold() == requested.casefold()
        ]
        if not matches:
            return _failed(step, "PAIRED_DEVICE_NOT_FOUND")
        if len(matches) > 1:
            return _failed(step, "PAIRED_DEVICE_LABEL_AMBIGUOUS")
        target = matches[0]
    elif len(devices) > 1:
        return _failed(step, "PAIRED_DEVICE_AMBIGUOUS")
    else:
        target = devices[0]

    gateway.revoke(target.device_id)

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:mobile_pairing_gateway",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_controlled_write",
                    "device_id": str(target.device_id),
                    "device_label": target.device_label,
                    "revoked_at": timestamp.isoformat(),
                },
            )
        ],
    )


def _execute_memory_remember(
    step: PlanStep,
    timestamp: datetime,
    memory_store: MemoryStore,
) -> CapabilityResult:
    """Store a user-asserted claim.

    Everything entering through this capability is USER_ASSERTED by
    definition: the person typed it. Web-derived claims arrive through the
    study pipeline at PUBLIC_WEB trust, never through here.
    """
    statement = str(step.parameters.get("statement", "")).strip()
    topic = str(step.parameters.get("topic", "")).strip() or "general"
    if not statement:
        return _failed(step, "MEMORY_STATEMENT_MISSING")
    try:
        claim = memory_store.remember(
            topic=topic,
            statement=statement,
            source_ref="user",
            source_trust=SourceTrust.USER_ASSERTED,
            confidence=0.95,
            volatility=Volatility.STABLE,
            now=timestamp,
        )
    except MemoryWriteRefused as exc:
        return _failed(step, str(exc).split(":", maxsplit=1)[0])
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:memory_store",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_controlled_write",
                    "claim_id": str(claim.claim_id),
                    "topic": claim.topic,
                    "source_trust": claim.source_trust.value,
                    "confidence": claim.confidence,
                },
            )
        ],
    )


def _execute_memory_recall(
    step: PlanStep,
    timestamp: datetime,
    memory_store: MemoryStore,
) -> CapabilityResult:
    query = str(step.parameters.get("query", "")).strip()
    if not query:
        return _failed(step, "MEMORY_QUERY_MISSING")
    matches = memory_store.recall(query, limit=5, now=timestamp)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:memory_store",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_readonly",
                    "query": query,
                    "match_count": len(matches),
                    "matches": [
                        {
                            "statement": match.claim.statement,
                            "topic": match.claim.topic,
                            "source_ref": match.claim.source_ref,
                            "source_trust": match.claim.source_trust.value,
                            "confidence": round(match.decayed_confidence, 3),
                            "score": round(match.score, 3),
                            "observed_at": match.claim.observed_at.isoformat(),
                        }
                        for match in matches
                    ],
                },
            )
        ],
    )


def _execute_memory_forget(
    step: PlanStep,
    timestamp: datetime,
    memory_store: MemoryStore,
) -> CapabilityResult:
    topic = str(step.parameters.get("topic", "")).strip()
    if not topic:
        return _failed(step, "MEMORY_TOPIC_MISSING")
    removed = memory_store.forget_topic(topic)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:memory_store",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_controlled_write",
                    "topic": topic,
                    "claims_removed": removed,
                },
            )
        ],
    )


_GREETING_REPLY = (
    "Hello. I can research public sources, remember things you tell me, "
    "control the media workspace, and send approved actions to your paired phone."
)
_THANKS_REPLY = "You're welcome."
_FAREWELL_REPLY = "Goodbye. Everything is recorded in your Action Receipts."
_WELLBEING_REPLY = (
    "Operating normally. Capabilities are registered, policy is active, and the "
    "Constitution verified on load."
)

_SMALL_TALK_REPLIES = {
    "greeting": _GREETING_REPLY,
    "thanks": _THANKS_REPLY,
    "farewell": _FAREWELL_REPLY,
    "wellbeing": _WELLBEING_REPLY,
}


def _execute_assistant_converse(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    """Answer a courtesy or a clock question.

    The clock is read from this machine, not inferred, so the answer is a fact
    rather than a guess. Nothing external is consulted and nothing is written.
    """
    field = str(step.parameters.get("datetime_field", "")).strip()
    if field:
        local = timestamp.astimezone()
        if field == "date":
            reply = f"Today is {local.strftime('%A, %d %B %Y')}."
        else:
            reply = f"It is {local.strftime('%H:%M')} on {local.strftime('%A, %d %B %Y')}."
        attributes: dict[str, object] = {
            "source_mode": "live_local_readonly",
            "reply": reply,
            "answer_path": "system_clock",
            "observed_at_local": local.isoformat(),
        }
    else:
        kind = str(step.parameters.get("small_talk_kind", "greeting"))
        reply = _SMALL_TALK_REPLIES.get(kind, _GREETING_REPLY)
        attributes = {
            "source_mode": "live_local_readonly",
            "reply": reply,
            "answer_path": "conversational",
            "small_talk_kind": kind,
        }

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:assistant",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )


# A recalled claim must clear this before Nexuss answers from memory instead of
# looking the question up. Below it, memory is a hint, not an answer.
_MEMORY_ANSWER_THRESHOLD = 0.35


def _execute_knowledge_answer(
    step: PlanStep,
    timestamp: datetime,
    memory_store: MemoryStore | None,
    knowledge_provider: KnowledgeProvider,
) -> CapabilityResult:
    """Answer from memory when memory is confident, from public sources when not.

    The two paths are never blended. An answer states which one produced it, so
    "you told me this" is never confused with "a public source says this", and
    web-derived claims keep public_web trust wherever they travel.
    """
    question = str(step.parameters.get("question", "")).strip()
    if not question:
        return _failed(step, "QUESTION_MISSING")

    remembered = memory_store.recall(question, limit=3, now=timestamp) if memory_store else ()
    confident = [match for match in remembered if match.score >= _MEMORY_ANSWER_THRESHOLD]

    if confident:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="local:memory_store",
                    observed_at=timestamp,
                    attributes={
                        "source_mode": "live_local_readonly",
                        "answer_path": "memory",
                        "question": question,
                        "match_count": len(confident),
                        "matches": [
                            {
                                "statement": match.claim.statement,
                                "source_ref": match.claim.source_ref,
                                "source_trust": match.claim.source_trust.value,
                                "confidence": round(match.decayed_confidence, 3),
                            }
                            for match in confident
                        ],
                    },
                )
            ],
        )

    try:
        research = knowledge_provider.research(question)
    except KnowledgeProviderError as exc:
        return _failed(step, str(exc))

    attributes = dict(research)
    attributes["answer_path"] = "public_web"
    attributes["question"] = question
    attributes["memory_checked"] = True
    # Anything from a public source stays untrusted data wherever it travels.
    attributes["content_trust"] = "untrusted_external_source"
    attributes["memory_saved"] = False

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="public_web:knowledge_provider",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )


def execute_step(
    step: PlanStep,
    observed_at: datetime | None = None,
    *,
    note_store: ManagedNoteStore | None = None,
    device_client: DeviceNodeClient | None = None,
    task_id: UUID | None = None,
    knowledge_provider: KnowledgeProvider | None = None,
    youtube_provider: YouTubeProvider | None = None,
    session_id: UUID | None = None,
    pairing_gateway: PhonePairingGateway | None = None,
    memory_store: MemoryStore | None = None,
) -> CapabilityResult:
    timestamp = observed_at or datetime.now(UTC)

    if step.capability_id == "assistant.converse":
        return _execute_assistant_converse(step, timestamp)

    if step.capability_id == "knowledge.answer":
        if knowledge_provider is None:
            return _failed(step, "KNOWLEDGE_PROVIDER_NOT_CONFIGURED")
        return _execute_knowledge_answer(
            step, timestamp, memory_store, knowledge_provider
        )

    if step.capability_id in {"memory.remember", "memory.recall", "memory.forget"}:
        if memory_store is None:
            return _failed(step, "MEMORY_STORE_NOT_CONFIGURED")
        if step.capability_id == "memory.remember":
            return _execute_memory_remember(step, timestamp, memory_store)
        if step.capability_id == "memory.recall":
            return _execute_memory_recall(step, timestamp, memory_store)
        return _execute_memory_forget(step, timestamp, memory_store)

    if step.capability_id == "device.pair_phone":
        if pairing_gateway is None or session_id is None:
            return _failed(step, "MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED")
        return _execute_pair_phone(step, timestamp, session_id, pairing_gateway)

    if step.capability_id == "device.list_phones":
        if pairing_gateway is None:
            return _failed(step, "MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED")
        return _execute_list_phones(step, timestamp, pairing_gateway)

    if step.capability_id == "device.unpair_phone":
        if pairing_gateway is None:
            return _failed(step, "MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED")
        return _execute_unpair_phone(step, timestamp, pairing_gateway)

    if step.capability_id == "assistant.respond":
        return _execute_assistant_response(step, timestamp)

    if step.capability_id == "workspace.create_note":
        if note_store is None:
            raise RuntimeError(
                "ManagedNoteStore is required for controlled writes"
            )
        return _execute_create_note(step, timestamp, note_store)

    if step.capability_id == "device.launch_notepad":
        if task_id is None or device_client is None:
            return _failed(step, "TRUSTED_DEVICE_NODE_NOT_CONFIGURED")
        return _execute_launch_notepad(
            step,
            timestamp,
            task_id,
            device_client,
        )

    if step.capability_id == "knowledge.web_research":
        if knowledge_provider is None:
            return _failed(step, "KNOWLEDGE_PROVIDER_NOT_CONFIGURED")
        return _execute_web_research(
            step,
            timestamp,
            knowledge_provider,
        )

    if step.capability_id == "media.youtube.discover":
        if youtube_provider is None:
            return _failed(step, "YOUTUBE_PROVIDER_NOT_CONFIGURED")
        return _execute_youtube_discovery(
            step,
            timestamp,
            youtube_provider,
        )

    if step.capability_id == "phone.open_youtube":
        return _execute_phone_handoff(step, timestamp)

    if step.capability_id == "device.open_web_search":
        if task_id is None or device_client is None:
            return _failed(step, "TRUSTED_DEVICE_NODE_NOT_CONFIGURED")
        return _execute_web_search(
            step,
            timestamp,
            task_id,
            device_client,
        )

    if step.capability_id == "workspace.read_status":
        try:
            attributes = collect_local_workspace_status(
                observed_at=timestamp
            )
        except LocalWorkspaceEvidenceError:
            return _failed(
                step,
                "LOCAL_WORKSPACE_EVIDENCE_UNAVAILABLE",
            )
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="local:workspace",
                    observed_at=timestamp,
                    attributes=attributes,
                )
            ],
        )

    return execute_simulated_step(step, observed_at=timestamp)

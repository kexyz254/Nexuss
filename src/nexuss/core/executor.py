"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Capability execution router for verified local, public-web, media, and device actions.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Protocol
from uuid import UUID

from nexuss.cognitive.models import CognitiveMode
from nexuss.cognitive.runtime import create_cognitive_proposal
from nexuss.cognitive.service import CognitiveProposalError
from nexuss.commitments.models import PrepareDayRequest, WorkdayBrief
from nexuss.commitments.service import (
    CommitmentIntelligenceError,
    CommitmentIntelligenceService,
)
from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.models import RepositoryCreateApproval
from nexuss.connectors.github.runtime import get_github_connector
from nexuss.connectors.github.service import GitHubConnectorService
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
    ApprovalRequest,
    CapabilityResult,
    EvidenceRecord,
    PlanStep,
    StepStatus,
)
from nexuss.engineering.errors import EngineeringError
from nexuss.intelligence.context import ConversationContextStore
from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.knowledge import ExistingKnowledgeProviderAdapter
from nexuss.intelligence.models import (
    AnswerStyle,
    ContentSensitivity,
    IntelligenceMode,
    IntelligenceRequest,
)
from nexuss.intelligence.provider import ExtractiveReasoningProvider
from nexuss.intelligence.router import ProviderRouter
from nexuss.intelligence.service import IntelligenceService
from nexuss.intelligence.system import collect_system_intelligence
from nexuss.knowledge.provider import KnowledgeProvider, KnowledgeProviderError
from nexuss.local_control.client import (
    HttpLocalControlClient,
    LocalControlError,
)
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
    # P6.12 DEVICE FAILURE FIDELITY
    except DeviceCommandError as exc:
        return _failed(
            step,
            str(exc) or "TRUSTED_DEVICE_COMMAND_FAILED",
        )
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
    except DeviceCommandError as exc:
        return _failed(
            step,
            str(exc) or "TRUSTED_BROWSER_HANDOFF_FAILED",
        )
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
    statement = str(
        step.parameters.get("statement", "")
    ).strip()
    topic = (
        str(step.parameters.get("topic", "")).strip()
        or "general"
    )

    normalized_statement = " ".join(
        statement.casefold().split()
    ).strip(" .!?")

    if normalized_statement in {
        "that",
        "this",
        "it",
        "that information",
        "this information",
        "the above",
    }:
        return _failed(
            step,
            "MEMORY_STATEMENT_AMBIGUOUS",
        )

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
_INTELLIGENCE_CONTEXT = ConversationContextStore()


_MEMORY_ANSWER_THRESHOLD = 0.70

_KNOWLEDGE_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9'\-]*"
)

_KNOWLEDGE_STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


def _knowledge_terms(value: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _KNOWLEDGE_TOKEN_PATTERN.finditer(value)
        if match.group(0).casefold()
        not in _KNOWLEDGE_STOP_WORDS
    }


def _memory_match_is_relevant(
    question: str,
    statement: str,
) -> bool:
    question_terms = _knowledge_terms(question)
    statement_terms = _knowledge_terms(statement)

    if not question_terms or not statement_terms:
        return False

    shared = question_terms & statement_terms
    overlap = len(shared) / len(question_terms)

    return bool(shared) and overlap >= 0.34



def _execute_knowledge_answer(
    step: PlanStep,
    timestamp: datetime,
    memory_store: MemoryStore | None,
    knowledge_provider: KnowledgeProvider,
    session_id: UUID | None,
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
    confident = [
        match
        for match in remembered
        if (
            match.score >= _MEMORY_ANSWER_THRESHOLD
            and _memory_match_is_relevant(
                question,
                match.claim.statement,
            )
        )
    ]

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
        intelligence = IntelligenceService(
            retriever=ExistingKnowledgeProviderAdapter(
                knowledge_provider
            ),
            provider_router=ProviderRouter(
                local_provider=ExtractiveReasoningProvider(),
            ),
            context_store=_INTELLIGENCE_CONTEXT,
        )

        answer = intelligence.answer(
            IntelligenceRequest(
                session_id=session_id or step.step_id,
                query=question,
                style=AnswerStyle.DETAILED,
                mode=IntelligenceMode.LOCAL_ONLY,
                sensitivity=ContentSensitivity.PUBLIC,
                external_processing_approved=False,
                requires_live_sources=False,
                max_sources=5,
                max_evidence_chars=12_000,
            )
        )
    except IntelligenceError as exc:
        return _failed(step, exc.code)

    sources = [
        {
            "source_id": source.source_id,
            "title": source.title,
            "url": (
                str(source.url)
                if source.url is not None
                else None
            ),
            "publisher": source.publisher,
            "published_at": (
                source.published_at.isoformat()
                if source.published_at is not None
                else None
            ),
            "retrieved_at": source.retrieved_at.isoformat(),
            "live": source.live,
        }
        for source in answer.sources
    ]

    attributes: dict[str, object] = {
        # Preserve the existing renderer contract.
        "answer_path": "public_web",
        "question": question,
        "brief": answer.answer,
        "sources": sources,

        # Intelligence-plane evidence.
        "answer": answer.answer,
        "claims": [
            claim.model_dump(mode="json")
            for claim in answer.claims
        ],
        "limitations": list(answer.limitations),
        "provider_id": answer.provider_id,
        "provider_kind": answer.provider_kind.value,
        "intelligence_mode": answer.intelligence_mode.value,
        "context": answer.context.model_dump(mode="json"),
        "grounded": answer.grounded,
        "verified": answer.verified,

        # Trust boundary.
        "source_mode": (
            "live_public_web_local_intelligence"
        ),
        "memory_checked": True,
        "content_trust": "untrusted_external_source",
        "memory_saved": False,
        "external_processing": False,
    }

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:intelligence_plane",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )




def _execute_github_status(
    step: PlanStep,
    timestamp: datetime,
    connector: GitHubConnectorService,
) -> CapabilityResult:
    try:
        health = connector.health(now=timestamp)
    except ConnectorError as exc:
        return _failed(step, exc.code)
    identity = health.identity
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="connector:github",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_github_readonly",
                    "status": health.status.value,
                    "configured": health.configured,
                    "detail": health.detail,
                    "account_login": (
                        identity.account_label if identity else None
                    ),
                    "account_id": (
                        identity.external_account_id if identity else None
                    ),
                    "account_type": (
                        identity.account_type if identity else None
                    ),
                    "identity_verified": (
                        identity.verified if identity else False
                    ),
                    "credentials_exposed": False,
                },
            )
        ],
    )


def _execute_github_repositories(
    step: PlanStep,
    timestamp: datetime,
    connector: GitHubConnectorService,
) -> CapabilityResult:
    try:
        inventory = connector.list_repositories(now=timestamp)
    except ConnectorError as exc:
        return _failed(step, exc.code)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="connector:github",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_github_readonly",
                    "account_login": inventory.account_login,
                    "total": inventory.total,
                    "private_count": inventory.private_count,
                    "public_count": inventory.public_count,
                    "archived_count": inventory.archived_count,
                    "disabled_count": inventory.disabled_count,
                    "fork_count": inventory.fork_count,
                    "repositories": [
                        {
                            "repository_id": repository.repository_id,
                            "name": repository.name,
                            "full_name": repository.full_name,
                            "private": repository.private,
                            "archived": repository.archived,
                            "disabled": repository.disabled,
                            "fork": repository.fork,
                            "html_url": str(repository.html_url),
                            "default_branch": repository.default_branch,
                            "updated_at": (
                                repository.updated_at.isoformat()
                                if repository.updated_at
                                else None
                            ),
                        }
                        for repository in inventory.repositories[:50]
                    ],
                    "credentials_exposed": False,
                },
            )
        ],
    )


def _execute_github_create_repository(
    step: PlanStep,
    timestamp: datetime,
    connector: GitHubConnectorService,
    approval: ApprovalRequest | None,
) -> CapabilityResult:
    if approval is None:
        return _failed(step, "GITHUB_APPROVAL_CONTEXT_MISSING")
    requested_name = str(
        step.parameters.get("requested_name", "")
    ).strip()
    expected_name = str(
        step.parameters.get("repository_name", "")
    ).strip()
    expected_account = str(
        step.parameters.get("account_login", "")
    ).strip()
    expected_digest = str(
        step.parameters.get("connector_payload_sha256", "")
    ).strip()
    try:
        prepared = connector.prepare_private_repository(
            requested_name,
            now=timestamp,
        )
    except ConnectorError as exc:
        return _failed(step, exc.code)
    if (
        prepared.repository_name != expected_name
        or prepared.owner_login.casefold() != expected_account.casefold()
        or prepared.payload_sha256 != expected_digest
    ):
        return _failed(step, "GITHUB_PREPARED_PAYLOAD_MISMATCH")
    connector_approval = RepositoryCreateApproval(
        approval_id=approval.approval_id,
        request_id=prepared.request_id,
        account_login=expected_account,
        payload_sha256=prepared.payload_sha256,
        approved_at=timestamp,
        expires_at=approval.expires_at,
    )
    try:
        verified = connector.create_private_repository(
            prepared,
            connector_approval,
            now=timestamp,
        )
    except ConnectorError as exc:
        return _failed(step, exc.code)
    repository = verified.repository
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="connector:github",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_github_controlled_write",
                    "repository_id": repository.repository_id,
                    "node_id": repository.node_id,
                    "owner_login": repository.owner_login,
                    "name": repository.name,
                    "full_name": repository.full_name,
                    "private": repository.private,
                    "html_url": str(repository.html_url),
                    "api_url": str(repository.api_url),
                    "initial_commit": False,
                    "private_verified": verified.private_verified,
                    "empty_repository_verified": (
                        verified.empty_repository_verified
                    ),
                    "owner_verified": verified.owner_verified,
                    "name_verified": verified.name_verified,
                    "approval_id": str(verified.approval_id),
                    "connector_payload_sha256": verified.payload_sha256,
                    "credentials_exposed": False,
                },
            )
        ],
    )


def _execute_system_intelligence(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    attributes = collect_system_intelligence(observed_at=timestamp)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:system_intelligence",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
    )


def _workday_brief_display(brief: WorkdayBrief) -> str:
    lines = [
        (
            f"Operational brief for {brief.planning_date.isoformat()}: "
            f"{len(brief.commitments)} commitments, "
            f"{brief.urgent_count} urgent, {brief.overdue_count} overdue, "
            f"{brief.responses_needed} responses needed."
        ),
        (
            f"Calendar: {len(brief.calendar_events)} events, "
            f"{len(brief.conflicts)} conflicts, "
            f"{len(brief.focus_blocks)} suggested focus blocks."
        ),
    ]

    if brief.commitments:
        lines.append("Top commitments:")
        for item in brief.commitments[:5]:
            due = (
                item.due_at.isoformat(timespec="minutes")
                if item.due_at is not None
                else "no fixed due time"
            )
            counterparty = (
                f" · {item.counterparty}"
                if item.counterparty
                else ""
            )
            lines.append(
                f"- {item.priority.value.upper()}: {item.summary}"
                f"{counterparty} · {due}"
            )

    if brief.conflicts:
        lines.append("Calendar conflicts:")
        for conflict in brief.conflicts[:3]:
            lines.append(
                f"- {conflict.first_title} ↔ {conflict.second_title} "
                f"({conflict.minutes} min overlap)"
            )

    if brief.focus_blocks:
        lines.append("Suggested focus blocks:")
        for block in brief.focus_blocks[:4]:
            lines.append(
                f"- {block.start.strftime('%H:%M')}–"
                f"{block.end.strftime('%H:%M')}: {block.title}"
            )

    unavailable = [
        name
        for name, available in brief.source_status.items()
        if not available
    ]
    if unavailable:
        lines.append(
            "Unavailable sources: " + ", ".join(sorted(unavailable)) + "."
        )

    lines.append(
        "Read-only brief: no email, calendar, contact, mobile, or external "
        "write was performed."
    )
    return "\n".join(lines)


def _execute_prepare_day(
    step: PlanStep,
    timestamp: datetime,
    commitment_service: CommitmentIntelligenceService | None,
) -> CapabilityResult:
    if commitment_service is None:
        return _failed(step, "COMMITMENT_INTELLIGENCE_NOT_CONFIGURED")

    timezone_name = str(
        step.parameters.get("timezone", "Africa/Nairobi")
    ).strip() or "Africa/Nairobi"
    include_mobile = bool(
        step.parameters.get("include_mobile", True)
    )

    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _failed(step, "COMMITMENT_TIMEZONE_INVALID")

    try:
        brief = commitment_service.prepare_day(
            PrepareDayRequest(
                planning_date=timestamp.astimezone(zone).date(),
                timezone=timezone_name,
                include_mobile=include_mobile,
            ),
            now=timestamp,
        )
    except CommitmentIntelligenceError as exc:
        return _failed(step, exc.code)

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:commitment_intelligence",
                observed_at=timestamp,
                attributes={
                    "display_text": _workday_brief_display(brief),
                    "workday_brief": brief.model_dump(mode="json"),
                    "source_status": brief.source_status,
                    "external_write_performed": (
                        brief.external_write_performed
                    ),
                    "phone_approval_requested": (
                        brief.phone_approval_requested
                    ),
                    "credentials_exposed": brief.credentials_exposed,
                    "source_mode": (
                        "cross_channel_readonly_intelligence"
                    ),
                },
            )
        ],
    )


def _execute_update_inspect(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    try:
        status = HttpLocalControlClient.from_environment().inspect_update()
    except (LocalControlError, ValueError) as exc:
        return _failed(step, str(exc))

    current = status.current_sha[:12]
    remote = status.remote_sha[:12]
    if not status.update_available:
        display = (
            f"Nexuss is up to date on {status.branch} at {current}. "
            "The local worktree is clean and no update is required."
        )
    elif status.clean_worktree and status.fast_forward_available:
        display = (
            f"A Nexuss update is available on {status.branch}: "
            f"{current} → {remote}. The local worktree is clean and the "
            "update can be fast-forwarded safely. Say “Update Nexuss” "
            "to prepare the exact approval."
        )
    else:
        display = (
            f"GitHub differs from the local Nexuss revision "
            f"({current} → {remote}), but a safe automatic fast-forward "
            f"is not currently available. clean_worktree="
            f"{status.clean_worktree}; fast_forward_available="
            f"{status.fast_forward_available}; ahead={status.ahead_by}; "
            f"behind={status.behind_by}."
        )

    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:trusted_control",
                observed_at=timestamp,
                attributes={
                    **status.model_dump(mode="json"),
                    "display_text": display,
                    "source_mode": "trusted_local_control_readonly",
                },
            )
        ],
    )


def _execute_update_result(
    step: PlanStep,
    timestamp: datetime,
) -> CapabilityResult:
    try:
        result = HttpLocalControlClient.from_environment().update_result()
    except (LocalControlError, ValueError) as exc:
        return _failed(step, str(exc))

    display = (
        "Last Nexuss update: "
        f"{result.status.replace('_', ' ')}. "
        f"{result.detail}"
    )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:trusted_control",
                observed_at=timestamp,
                attributes={
                    **result.model_dump(mode="json"),
                    "display_text": display,
                    "source_mode": "trusted_local_control_readonly",
                },
            )
        ],
    )


def _execute_update_apply(
    step: PlanStep,
    timestamp: datetime,
    approval: ApprovalRequest | None,
) -> CapabilityResult:
    if approval is None:
        return _failed(step, "LOCAL_UPDATE_APPROVAL_CONTEXT_MISSING")

    current_sha = str(
        step.parameters.get("expected_current_sha", "")
    )
    target_sha = str(
        step.parameters.get("expected_target_sha", "")
    )

    try:
        accepted = HttpLocalControlClient.from_environment().apply_update(
            expected_current_sha=current_sha,
            expected_target_sha=target_sha,
        )
    except (LocalControlError, ValueError) as exc:
        return _failed(step, str(exc))

    display = (
        f"Nexuss accepted the verified update "
        f"{accepted.previous_sha[:12]} → {accepted.target_sha[:12]}. "
        "A restart is scheduled and failed startup health will trigger "
        "automatic rollback. After the runtime returns, Nexuss will verify "
        "the retained update result."
    )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:trusted_control",
                observed_at=timestamp,
                attributes={
                    **accepted.model_dump(mode="json"),
                    "display_text": display,
                    "approval_id": str(approval.approval_id),
                    "source_mode": "trusted_local_control_verified_update",
                    "arbitrary_shell_enabled": False,
                },
            )
        ],
    )


def _execute_cognitive_proposal(
    step: PlanStep,
    timestamp: datetime,
    task_id: UUID | None,
) -> CapabilityResult:
    instruction = str(
        step.parameters.get("instruction", "")
    ).strip()
    raw_mode = str(
        step.parameters.get("mode", "analyze")
    ).strip()

    if not instruction:
        return _failed(step, "COGNITIVE_INSTRUCTION_EMPTY")

    try:
        mode = CognitiveMode(raw_mode)
    except ValueError:
        return _failed(step, "COGNITIVE_MODE_INVALID")

    try:
        envelope = create_cognitive_proposal(
            request_id=task_id or step.step_id,
            instruction=instruction,
            mode=mode,
        )
    except CognitiveProposalError as exc:
        return _failed(step, exc.code)
    except EngineeringError as exc:
        return _failed(step, exc.code)

    proposal = envelope.proposal
    receipt = envelope.receipt
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="provider:cognitive",
                observed_at=timestamp,
                attributes={
                    "display_text": proposal.response,
                    "summary": proposal.summary,
                    "mode": proposal.mode.value,
                    "provider_id": proposal.provider_id,
                    "model": proposal.model,
                    "steps": list(proposal.steps),
                    "assumptions": list(proposal.assumptions),
                    "risks": list(proposal.risks),
                    "recommended_actions": list(
                        proposal.recommended_actions
                    ),
                    "receipt_id": str(receipt.receipt_id),
                    "request_sha256": receipt.request_sha256,
                    "response_sha256": receipt.response_sha256,
                    "provider_generated_proposal_only": True,
                    "execution_authorized": False,
                    "external_writes": False,
                    "credentials_exposed": False,
                },
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
    commitment_service: CommitmentIntelligenceService | None = None,
    github_connector: GitHubConnectorService | None = None,
    approval: ApprovalRequest | None = None,
) -> CapabilityResult:
    timestamp = observed_at or datetime.now(UTC)

    if step.capability_id == "system.runtime.inspect":
        return _execute_system_intelligence(step, timestamp)

    if step.capability_id == "commitments.prepare_day":
        return _execute_prepare_day(
            step,
            timestamp,
            commitment_service,
        )

    if step.capability_id == "system.update.inspect":
        return _execute_update_inspect(step, timestamp)

    if step.capability_id == "system.update.result":
        return _execute_update_result(step, timestamp)

    if step.capability_id == "system.update.apply":
        return _execute_update_apply(
            step,
            timestamp,
            approval,
        )

    if step.capability_id in {
        "github.connection.status",
        "github.repositories.list",
        "github.repository.create",
    }:
        connector = (
            github_connector
            if github_connector is not None
            else get_github_connector()
        )
        if step.capability_id == "github.connection.status":
            return _execute_github_status(step, timestamp, connector)
        if step.capability_id == "github.repositories.list":
            return _execute_github_repositories(
                step,
                timestamp,
                connector,
            )
        return _execute_github_create_repository(
            step,
            timestamp,
            connector,
            approval,
        )

    if step.capability_id.startswith("intelligence."):
        return _execute_cognitive_proposal(
            step,
            timestamp,
            task_id,
        )

    if step.capability_id == "assistant.converse":
        return _execute_assistant_converse(step, timestamp)

    if step.capability_id == "knowledge.answer":
        if knowledge_provider is None:
            return _failed(step, "KNOWLEDGE_PROVIDER_NOT_CONFIGURED")
        return _execute_knowledge_answer(
            step,
            timestamp,
            memory_store,
            knowledge_provider,
            session_id,
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

    if step.capability_id == "engineering.build_artifact":
        from nexuss.engineering.prompt_build import execute_prompt_build

        return execute_prompt_build(step, timestamp, task_id=task_id)

    if step.capability_id == "engineering.repair_failed_build":
        from nexuss.engineering.prompt_build import execute_latest_failed_build_repair

        return execute_latest_failed_build_repair(
            step,
            timestamp,
            task_id=task_id,
        )

    if step.capability_id == "engineering.verify_acceptance":
        from nexuss.engineering.acceptance import collect_engineering_acceptance

        attributes = collect_engineering_acceptance(
            target=str(
                step.parameters.get("target", "current engineering phase")
            ),
            observed_at=timestamp,
        )
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="local:engineering_acceptance",
                    observed_at=timestamp,
                    attributes={
                        "engineering_acceptance_receipt": attributes,
                        **attributes,
                    },
                )
            ],
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

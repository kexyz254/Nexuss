from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.collaboration.crypto import sha256_json
from nexuss.collaboration.models import (
    ActionPlanPayload,
    CapabilityLeaseEntry,
    CapabilityLeasePayload,
    EvidenceItem,
    EvidencePayload,
    IntentPayload,
    MessageKind,
)
from nexuss.collaboration.service import (
    CollaborationProtocolError,
    CollaborationProtocolService,
)
from nexuss.collaboration.store import SQLiteCollaborationStore


def build_service(tmp_path: Path) -> CollaborationProtocolService:
    return CollaborationProtocolService(
        store=SQLiteCollaborationStore(
            tmp_path / "collaboration.sqlite3"
        )
    )


def start(service: CollaborationProtocolService):
    instruction = "Inspect my GitHub repositories."
    intent = IntentPayload(
        instruction=instruction,
        instruction_sha256=hashlib.sha256(
            instruction.encode()
        ).hexdigest(),
        context_sha256=hashlib.sha256(b"").hexdigest(),
        privacy_classification="private",
        maximum_rounds=4,
        maximum_actions_per_round=4,
    )
    entries = (
        CapabilityLeaseEntry(
            capability_id="github.repositories.list",
            risk_tier="low",
            approval_policy="none",
            execution_mode="live_github_readonly",
            provider_can_request=True,
        ),
    )
    lease = CapabilityLeasePayload(
        catalog_sha256=sha256_json(
            [entry.model_dump(mode="json") for entry in entries]
        ),
        lease_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        capabilities=entries,
    )
    return service.create_session(
        request_id=uuid4(),
        user_session_id=uuid4(),
        provider_id="deepseek",
        model="deepseek-v4-pro",
        intent=intent,
        lease=lease,
    )


def test_valid_request_evidence_loop(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    session, _intent, lease = start(service)
    plan = ActionPlanPayload(
        summary="Inspect repositories.",
        user_facing_response="I will request repository inventory.",
        requested_actions=(
            {
                "action_key": "list_repositories",
                "capability_id": "github.repositories.list",
                "arguments": {},
                "rationale": "Read the verified inventory.",
                "expected_evidence": (
                    "github_repository_inventory",
                ),
                "depends_on": (),
            },
        ),
    )
    session, provider_message = service.accept_provider_message(
        session_id=session.session_id,
        kind=MessageKind.ACTION_PLAN,
        payload=plan,
        reply_to_message_id=lease.message_id,
    )
    evidence = EvidencePayload(
        items=(
            EvidenceItem(
                action_key="list_repositories",
                capability_id="github.repositories.list",
                status="verified",
                source="nexuss:github",
                evidence_sha256="a" * 64,
                receipt_id=uuid4(),
                summary="Repository inventory verified.",
            ),
        ),
        all_items_verified=True,
    )
    session, _message = service.send_nexuss_message(
        session_id=session.session_id,
        kind=MessageKind.EVIDENCE,
        payload=evidence,
        reply_to_message_id=provider_message.message_id,
    )
    transcript = service.transcript(session.session_id)

    assert len(transcript) == 4
    assert transcript[-1].kind is MessageKind.EVIDENCE
    assert session.state.value == "waiting_for_provider"


def test_replay_reply_is_rejected(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    session, intent, lease = start(service)
    plan = ActionPlanPayload(
        summary="Inspect repositories.",
        user_facing_response="Request inventory.",
    )
    service.accept_provider_message(
        session_id=session.session_id,
        kind=MessageKind.ACTION_PLAN,
        payload=plan,
        reply_to_message_id=lease.message_id,
    )

    with pytest.raises(
        CollaborationProtocolError,
        match="not waiting for a provider",
    ):
        service.accept_provider_message(
            session_id=session.session_id,
            kind=MessageKind.ACTION_PLAN,
            payload=plan,
            reply_to_message_id=intent.message_id,
        )


def test_hash_chain_is_verified(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    session, _intent, _lease = start(service)
    messages = service.transcript(session.session_id)

    assert len(messages) == 2
    assert messages[1].previous_message_sha256 == (
        messages[0].message_sha256
    )

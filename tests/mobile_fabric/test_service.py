"""P6.7A mobile fabric service tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexuss.mobile_fabric.models import (
    MobileActionDecision,
    MobileActionEvidence,
    MobileActionKind,
    MobileActionPrepareRequest,
    MobileActionState,
    MobileDecisionKind,
    MobileSignal,
    MobileSignalBatch,
    MobileSignalKind,
    MobileSource,
)
from nexuss.mobile_fabric.service import MobileFabricError, MobileFabricService


def _batch() -> MobileSignalBatch:
    return MobileSignalBatch(
        sequence=1,
        device_time=datetime.now(UTC),
        batch_nonce="n" * 32,
        signals=(
            MobileSignal(
                source=MobileSource.WHATSAPP,
                package_name="com.whatsapp",
                kind=MobileSignalKind.MESSAGE_RECEIVED,
                occurred_at=datetime.now(UTC),
                sender_label="Amina",
                conversation_label="Amina",
                text="Please send the draft today.",
                notification_key="whatsapp:1",
                reply_supported=True,
            ),
            MobileSignal(
                source=MobileSource.PHONE,
                package_name="com.google.android.dialer",
                kind=MobileSignalKind.MISSED_CALL,
                occurred_at=datetime.now(UTC),
                sender_label="Peter",
            ),
        ),
    )


def test_signal_ingestion_deduplicates_and_summarizes() -> None:
    service = MobileFabricService()
    device_id = uuid4()

    batch = _batch()
    first = service.ingest(device_id=device_id, batch=batch)
    second = service.ingest(device_id=device_id, batch=batch)
    summary = service.attention_summary()

    assert first.accepted == 2
    assert second.duplicates == 2
    assert summary.unread_like_messages == 1
    assert summary.missed_calls == 1
    assert summary.reply_capable_notifications == 1


def test_action_requires_exact_biometric_approval_and_evidence() -> None:
    service = MobileFabricService()
    device_id = uuid4()
    proposal = service.prepare_action(
        MobileActionPrepareRequest(
            device_id=device_id,
            kind=MobileActionKind.NOTIFICATION_REPLY,
            source=MobileSource.WHATSAPP,
            target_label="Amina",
            body="I will send it by 4 PM.",
            notification_key="whatsapp:1",
        )
    )

    assert proposal.state is MobileActionState.PREPARED
    assert proposal.external_write_performed is False

    with pytest.raises(MobileFabricError) as exc_info:
        service.decide(
            device_id=device_id,
            action_id=proposal.proposal.action_id,
            decision=MobileActionDecision(
                approval_token=proposal.proposal.approval_token,
                payload_sha256=proposal.proposal.payload_sha256,
                decision=MobileDecisionKind.APPROVE,
                biometric_verified=False,
                decided_at=datetime.now(UTC),
            ),
        )
    assert exc_info.value.code == "MOBILE_BIOMETRIC_REQUIRED"

    approved = service.decide(
        device_id=device_id,
        action_id=proposal.proposal.action_id,
        decision=MobileActionDecision(
            approval_token=proposal.proposal.approval_token,
            payload_sha256=proposal.proposal.payload_sha256,
            decision=MobileDecisionKind.APPROVE,
            biometric_verified=True,
            decided_at=datetime.now(UTC),
        ),
    )
    assert approved.state is MobileActionState.APPROVED
    assert approved.external_write_performed is False

    evidence_material = b"reply-dispatched"
    verified = service.record_evidence(
        device_id=device_id,
        action_id=proposal.proposal.action_id,
        evidence=MobileActionEvidence(
            action_id=proposal.proposal.action_id,
            payload_sha256=proposal.proposal.payload_sha256,
            executed=True,
            external_write_performed=True,
            verification_scope="dispatch_accepted",
            result_code="REMOTE_INPUT_SENT",
            provider_reference="notification:whatsapp:1",
            observed_at=datetime.now(UTC),
            evidence_sha256=hashlib.sha256(evidence_material).hexdigest(),
        ),
    )

    assert verified.state is MobileActionState.VERIFIED
    assert verified.external_write_performed is True
    assert verified.verified is True

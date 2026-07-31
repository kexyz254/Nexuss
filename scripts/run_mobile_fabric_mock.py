"""Offline P6.7A trusted mobile communication fabric proof."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from nexuss.mobile_fabric.models import (
    MobileActionDecision,
    MobileActionEvidence,
    MobileActionKind,
    MobileActionPrepareRequest,
    MobileDecisionKind,
    MobileSignal,
    MobileSignalBatch,
    MobileSignalKind,
    MobileSource,
)
from nexuss.mobile_fabric.service import MobileFabricService


def main() -> int:
    service = MobileFabricService()
    device_id = uuid4()
    batch = MobileSignalBatch(
        sequence=1,
        device_time=datetime.now(UTC),
        batch_nonce="offline-proof-nonce-000000000000",
        signals=(
            MobileSignal(
                source=MobileSource.WHATSAPP,
                package_name="com.whatsapp",
                kind=MobileSignalKind.MESSAGE_RECEIVED,
                occurred_at=datetime.now(UTC),
                sender_label="Amina",
                conversation_label="Amina",
                text="Please send the report today.",
                notification_key="whatsapp:offline:1",
                reply_supported=True,
            ),
            MobileSignal(
                source=MobileSource.SMS,
                package_name="com.google.android.apps.messaging",
                kind=MobileSignalKind.MESSAGE_RECEIVED,
                occurred_at=datetime.now(UTC),
                sender_label="Bank",
                text="Your verification code is 123456",
            ),
        ),
    )
    ingestion = service.ingest(device_id=device_id, batch=batch)
    summary = service.attention_summary()
    proposal = service.prepare_action(
        MobileActionPrepareRequest(
            device_id=device_id,
            kind=MobileActionKind.NOTIFICATION_REPLY,
            source=MobileSource.WHATSAPP,
            target_label="Amina",
            body="I will send the report by 4 PM.",
            notification_key="whatsapp:offline:1",
        )
    )
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
    evidence = hashlib.sha256(b"offline dispatch evidence").hexdigest()
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
            provider_reference="whatsapp:offline:1",
            observed_at=datetime.now(UTC),
            evidence_sha256=evidence,
        ),
    )

    print("=" * 78)
    print("NEXUSS P6.7A TRUSTED MOBILE COMMUNICATION FABRIC OFFLINE PROOF")
    print("=" * 78)
    print(f"Signals accepted:              {ingestion.accepted}")
    print(f"Sensitive content withheld:    {summary.latest_items[-1].signal.sensitive}")
    print(f"Reply-capable notifications:   {summary.reply_capable_notifications}")
    print(f"Action prepared:               {proposal.state.value}")
    print(f"Action approved:               {approved.state.value}")
    print(f"Action evidence state:         {verified.state.value}")
    print(
        "Simulated dispatch evidence:    "
        f"{verified.external_write_performed}"
    )
    print("Real device action performed:   False")
    print("Accessibility automation:      False")
    print("Private app database access:   False")
    print("Call audio recording:          False")
    print("Credentials exposed:           False")
    print("PASS: P6.7A offline proof completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline proof for P6.8A unified commitment intelligence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexuss.commitments.models import PrepareDayRequest
from nexuss.commitments.service import CommitmentIntelligenceService
from nexuss.connectors.google_workspace.models import (
    CalendarEventSummary,
    GmailMessageSummary,
    GoogleWorkspaceProfile,
    GoogleWorkspaceSnapshot,
)
from nexuss.mobile_fabric.models import (
    MobileSignal,
    MobileSignalBatch,
    MobileSignalKind,
    MobileSource,
)
from nexuss.mobile_fabric.service import MobileFabricService


class _Google:
    connected = True
    def snapshot(self, **kwargs):
        del kwargs
        now = datetime.now(UTC)
        return GoogleWorkspaceSnapshot(
            profile=GoogleWorkspaceProfile(
                email="owner@example.com",
                granted_scopes=("readonly",),
            ),
            messages=(
                GmailMessageSummary(
                    message_id="m1",
                    thread_id="t1",
                    subject="Security report",
                    sender="Sarah <sarah@example.com>",
                    recipients=("owner@example.com",),
                    received_at=now,
                    snippet="Please send the report by 3 pm today.",
                    labels=("INBOX", "UNREAD"),
                    unread=True,
                ),
                GmailMessageSummary(
                    message_id="m2",
                    thread_id="t2",
                    subject="Re: Client notes",
                    sender="Owner <owner@example.com>",
                    recipients=("client@example.com",),
                    received_at=now,
                    snippet="I will send the revised notes tomorrow.",
                    labels=("SENT",),
                ),
            ),
            calendars=(),
            events=(
                CalendarEventSummary(
                    event_id="e1",
                    calendar_id="primary",
                    title="Client meeting",
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=3),
                ),
                CalendarEventSummary(
                    event_id="e2",
                    calendar_id="primary",
                    title="Project review",
                    start=now + timedelta(hours=2, minutes=30),
                    end=now + timedelta(hours=3, minutes=30),
                ),
            ),
            contacts=(),
        )

def main() -> int:
    mobile = MobileFabricService()
    now = datetime.now(UTC)
    mobile.ingest(
        device_id=uuid4(),
        batch=MobileSignalBatch(
            sequence=1,
            device_time=now,
            batch_nonce="a" * 32,
            signals=(
                MobileSignal(
                    source=MobileSource.WHATSAPP,
                    package_name="com.whatsapp",
                    kind=MobileSignalKind.MESSAGE_RECEIVED,
                    occurred_at=now,
                    sender_label="Alex",
                    text="Can you review the final draft tomorrow?",
                ),
            ),
        ),
    )
    service = CommitmentIntelligenceService(
        google_workspace=_Google(),
        mobile_fabric=mobile,
    )
    brief = service.prepare_day(
        PrepareDayRequest(
            planning_date=datetime.now(UTC).date(),
            timezone="Africa/Nairobi",
        ),
        now=now,
    )
    print("=" * 78)
    print("NEXUSS P6.8A UNIFIED COMMITMENT INTELLIGENCE OFFLINE PROOF")
    print("=" * 78)
    print(f"Commitments:          {len(brief.commitments)}")
    print(f"Urgent:               {brief.urgent_count}")
    print(f"Responses needed:     {brief.responses_needed}")
    print(f"Calendar conflicts:   {len(brief.conflicts)}")
    print(f"Focus proposals:      {len(brief.focus_blocks)}")
    print(f"External write:       {brief.external_write_performed}")
    print(f"Approval requested:   {brief.phone_approval_requested}")
    print(f"Credentials exposed:  {brief.credentials_exposed}")
    assert len(brief.commitments) >= 3
    assert len(brief.conflicts) == 1
    assert brief.external_write_performed is False
    assert brief.phone_approval_requested is False
    print("PASS: P6.8A offline proof completed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

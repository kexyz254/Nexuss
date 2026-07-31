from datetime import UTC, datetime

from nexuss.commitments.extractor import extract_commitments
from nexuss.commitments.models import CommitmentKind
from nexuss.connectors.google_workspace.models import (
    GmailMessageSummary,
    GoogleWorkspaceProfile,
    GoogleWorkspaceSnapshot,
)


def test_extracts_request_promise_and_deadline() -> None:
    now = datetime(2026, 7, 31, 9, tzinfo=UTC)
    snapshot = GoogleWorkspaceSnapshot(
        profile=GoogleWorkspaceProfile(
            email="owner@example.com",
            granted_scopes=("readonly",),
        ),
        messages=(
            GmailMessageSummary(
                message_id="m1",
                thread_id="t1",
                subject="Report",
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
                subject="Notes",
                sender="Owner <owner@example.com>",
                recipients=("client@example.com",),
                received_at=now,
                snippet="I will send the notes tomorrow.",
                labels=("SENT",),
            ),
        ),
        calendars=(),
        events=(),
        contacts=(),
    )
    records = extract_commitments(
        snapshot=snapshot,
        mobile=None,
        now=now,
        timezone_name="Africa/Nairobi",
    )
    assert {record.kind for record in records} == {
        CommitmentKind.REQUEST,
        CommitmentKind.PROMISE,
    }
    assert any(record.due_at is not None for record in records)

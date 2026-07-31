from datetime import UTC, date, datetime, timedelta

from nexuss.commitments.models import PrepareDayRequest
from nexuss.commitments.service import CommitmentIntelligenceService
from nexuss.connectors.google_workspace.models import (
    CalendarEventSummary,
    GmailMessageSummary,
    GoogleWorkspaceProfile,
    GoogleWorkspaceSnapshot,
)


class GoogleStub:
    connected = True

    def snapshot(self, **kwargs):
        del kwargs
        now = datetime(2026, 7, 31, 9, tzinfo=UTC)
        return GoogleWorkspaceSnapshot(
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
                    snippet="Please send the report today.",
                    labels=("UNREAD",),
                    unread=True,
                ),
            ),
            calendars=(),
            events=(
                CalendarEventSummary(
                    event_id="e1",
                    calendar_id="primary",
                    title="Meeting",
                    start=now + timedelta(hours=2),
                    end=now + timedelta(hours=3),
                ),
            ),
            contacts=(),
        )


def test_prepare_day_is_read_only() -> None:
    brief = CommitmentIntelligenceService(
        google_workspace=GoogleStub()
    ).prepare_day(
        PrepareDayRequest(
            planning_date=date(2026, 7, 31),
            timezone="UTC",
        ),
        now=datetime(2026, 7, 31, 9, tzinfo=UTC),
    )
    assert brief.commitments
    assert brief.external_write_performed is False
    assert brief.phone_approval_requested is False
    assert brief.credentials_exposed is False

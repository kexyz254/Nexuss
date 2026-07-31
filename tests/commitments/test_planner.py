from datetime import UTC, date, datetime, timedelta

from nexuss.commitments.models import (
    CommitmentEvidence,
    CommitmentKind,
    CommitmentPriority,
    CommitmentRecord,
    CommitmentSource,
    CommitmentStatus,
)
from nexuss.commitments.planner import find_conflicts, propose_focus_blocks
from nexuss.connectors.google_workspace.models import CalendarEventSummary


def test_conflicts_and_focus_blocks_are_proposals() -> None:
    start = datetime(2026, 7, 31, 9, tzinfo=UTC)
    events = (
        CalendarEventSummary(
            event_id="a",
            calendar_id="primary",
            title="A",
            start=start,
            end=start + timedelta(hours=1),
        ),
        CalendarEventSummary(
            event_id="b",
            calendar_id="primary",
            title="B",
            start=start + timedelta(minutes=30),
            end=start + timedelta(hours=2),
        ),
    )
    commitment = CommitmentRecord(
        kind=CommitmentKind.REQUEST,
        summary="Send report",
        priority=CommitmentPriority.HIGH,
        status=CommitmentStatus.OPEN,
        confidence=0.9,
        evidence=(
            CommitmentEvidence(
                source=CommitmentSource.GMAIL,
                source_id="m1",
                excerpt="Please send report",
                observed_at=start,
                evidence_sha256="a" * 64,
            ),
        ),
        source_count=1,
    )
    assert find_conflicts(events)[0].minutes == 30
    blocks = propose_focus_blocks(
        commitments=(commitment,),
        events=events,
        planning_date=date(2026, 7, 31),
        timezone_name="UTC",
    )
    assert blocks
    assert "calendar unchanged" in blocks[0].rationale

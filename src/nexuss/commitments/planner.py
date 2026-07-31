"""Calendar-conflict detection and bounded focus-block planning."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nexuss.commitments.models import (
    CalendarConflict,
    CommitmentPriority,
    CommitmentRecord,
    FocusBlock,
)
from nexuss.connectors.google_workspace.models import CalendarEventSummary


def find_conflicts(
    events: tuple[CalendarEventSummary, ...],
) -> tuple[CalendarConflict, ...]:
    active = tuple(
        event
        for event in events
        if event.status != "cancelled" and not event.all_day
    )
    conflicts: list[CalendarConflict] = []
    for index, first in enumerate(active):
        for second in active[index + 1:]:
            overlap_start = max(first.start, second.start)
            overlap_end = min(first.end, second.end)
            if overlap_end <= overlap_start:
                continue
            conflicts.append(
                CalendarConflict(
                    first_event_id=first.event_id,
                    second_event_id=second.event_id,
                    first_title=first.title,
                    second_title=second.title,
                    overlap_start=overlap_start,
                    overlap_end=overlap_end,
                    minutes=max(
                        1,
                        int(
                            (overlap_end - overlap_start).total_seconds()
                            // 60
                        ),
                    ),
                )
            )
    return tuple(conflicts)

def propose_focus_blocks(
    *,
    commitments: tuple[CommitmentRecord, ...],
    events: tuple[CalendarEventSummary, ...],
    planning_date: date,
    timezone_name: str,
) -> tuple[FocusBlock, ...]:
    zone = ZoneInfo(timezone_name)
    work_start = datetime.combine(planning_date, time(hour=8), tzinfo=zone)
    work_end = datetime.combine(planning_date, time(hour=18), tzinfo=zone)
    busy = sorted(
        (
            max(work_start, event.start.astimezone(zone)),
            min(work_end, event.end.astimezone(zone)),
        )
        for event in events
        if (
            not event.all_day
            and event.status != "cancelled"
            and event.end.astimezone(zone) > work_start
            and event.start.astimezone(zone) < work_end
        )
    )
    windows: list[tuple[datetime, datetime]] = []
    cursor = work_start
    for start, end in busy:
        if start > cursor:
            windows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < work_end:
        windows.append((cursor, work_end))
    blocks: list[FocusBlock] = []
    candidates = [
        item
        for item in commitments
        if item.priority in {
            CommitmentPriority.CRITICAL,
            CommitmentPriority.HIGH,
            CommitmentPriority.MEDIUM,
        }
    ]
    for commitment in candidates:
        duration = timedelta(
            minutes=(
                60
                if commitment.priority in {
                    CommitmentPriority.CRITICAL,
                    CommitmentPriority.HIGH,
                }
                else 30
            )
        )
        for index, (start, end) in enumerate(windows):
            if end - start < duration:
                continue
            block_end = start + duration
            blocks.append(
                FocusBlock(
                    commitment_id=commitment.commitment_id,
                    title=commitment.summary,
                    start=start,
                    end=block_end,
                    rationale=(
                        f"{commitment.priority.value} priority; "
                        "proposal only, calendar unchanged"
                    ),
                )
            )
            windows[index] = (block_end, end)
            break
    return tuple(blocks)

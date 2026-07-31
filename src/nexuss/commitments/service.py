"""Unified Gmail, Calendar, Contacts, and mobile commitment service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nexuss.commitments.extractor import extract_commitments
from nexuss.commitments.models import (
    CommitmentHealth,
    CommitmentPriority,
    PrepareDayRequest,
    WorkdayBrief,
)
from nexuss.commitments.planner import find_conflicts, propose_focus_blocks
from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.google_workspace.models import GoogleWorkspaceSnapshot
from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)
from nexuss.mobile_fabric.models import MobileFeedSnapshot
from nexuss.mobile_fabric.service import MobileFabricService


class CommitmentIntelligenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

class CommitmentIntelligenceService:
    def __init__(
        self,
        *,
        google_workspace: GoogleWorkspaceConnectorService,
        mobile_fabric: MobileFabricService | None = None,
    ) -> None:
        self._google = google_workspace
        self._mobile = mobile_fabric

    def health(self) -> CommitmentHealth:
        return CommitmentHealth(
            google_workspace_connected=self._google.connected,
            trusted_mobile_feed_available=self._mobile is not None,
        )

    def prepare_day(
        self,
        request: PrepareDayRequest,
        *,
        now: datetime | None = None,
    ) -> WorkdayBrief:
        try:
            zone = ZoneInfo(request.timezone)
        except ZoneInfoNotFoundError as exc:
            raise CommitmentIntelligenceError(
                "COMMITMENT_TIMEZONE_INVALID",
                "The requested timezone is not installed.",
            ) from exc
        checked_at = now or datetime.now(UTC)
        local_start = datetime.combine(
            request.planning_date,
            datetime.min.time(),
            tzinfo=zone,
        )
        local_end = local_start + timedelta(days=1)
        snapshot = self._snapshot(
            time_min=local_start - timedelta(days=1),
            time_max=local_end + timedelta(days=14),
            gmail_days_back=request.gmail_days_back,
        )
        mobile = self._mobile_feed() if request.include_mobile else None
        commitments = extract_commitments(
            snapshot=snapshot,
            mobile=mobile,
            now=checked_at,
            timezone_name=request.timezone,
        )
        day_events = tuple(
            event
            for event in snapshot.events
            if (
                event.start.astimezone(zone) < local_end
                and event.end.astimezone(zone) > local_start
            )
        )
        conflicts = find_conflicts(day_events)
        focus_blocks = propose_focus_blocks(
            commitments=commitments,
            events=day_events,
            planning_date=request.planning_date,
            timezone_name=request.timezone,
        )
        return WorkdayBrief(
            planning_date=request.planning_date,
            timezone=request.timezone,
            connected_google_account=(
                snapshot.profile.email if snapshot.profile else None
            ),
            source_status={
                "gmail": snapshot.profile is not None,
                "calendar": snapshot.profile is not None,
                "contacts": snapshot.profile is not None,
                "mobile": mobile is not None,
            },
            commitments=commitments,
            calendar_events=day_events,
            conflicts=conflicts,
            focus_blocks=focus_blocks,
            urgent_count=sum(
                item.priority in {
                    CommitmentPriority.CRITICAL,
                    CommitmentPriority.HIGH,
                }
                for item in commitments
            ),
            overdue_count=sum(
                item.status.value == "overdue"
                for item in commitments
            ),
            responses_needed=sum(
                item.response_needed for item in commitments
            ),
        )

    def _snapshot(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        gmail_days_back: int,
    ) -> GoogleWorkspaceSnapshot:
        if not self._google.connected:
            return GoogleWorkspaceSnapshot(
                profile=None,
                messages=(),
                calendars=(),
                events=(),
                contacts=(),
            )
        try:
            return self._google.snapshot(
                time_min=time_min,
                time_max=time_max,
                gmail_query=f"newer_than:{gmail_days_back}d",
            )
        except ConnectorError as exc:
            raise CommitmentIntelligenceError(
                exc.code,
                exc.message,
            ) from exc

    def _mobile_feed(self) -> MobileFeedSnapshot | None:
        if self._mobile is None:
            return None
        return self._mobile.feed(after_cursor=0, limit=500)

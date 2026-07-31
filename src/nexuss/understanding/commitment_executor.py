"""Read-only execution adapter for commitment-intelligence goals."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from nexuss.commitments.models import PrepareDayRequest
from nexuss.commitments.service import CommitmentIntelligenceService
from nexuss.understanding.models import (
    GoalExecutionResult,
    GoalInterpretation,
    GoalKind,
)


class CommitmentGoalExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CommitmentGoalExecutor:
    def __init__(
        self,
        service: CommitmentIntelligenceService,
        *,
        timezone_name: str = "Africa/Nairobi",
    ) -> None:
        self._service = service
        self._timezone = timezone_name

    def execute(
        self,
        interpretation: GoalInterpretation,
    ) -> GoalExecutionResult:
        goal = interpretation.goal
        if goal is GoalKind.GOOGLE_WORKSPACE_STATUS:
            data = self._service.health().model_dump(mode="json")
            message = (
                "Unified commitment sources are ready. "
                f"Google Workspace connected: "
                f"{data['google_workspace_connected']}. "
                f"Trusted mobile feed available: "
                f"{data['trusted_mobile_feed_available']}. "
                "No external write was performed."
            )
            return self._result(
                "google_workspace_status",
                message,
                data,
            )

        brief = self._service.prepare_day(
            PrepareDayRequest(
                planning_date=datetime.now(UTC).date(),
                timezone=self._timezone,
            )
        )
        data = brief.model_dump(mode="json")

        if goal is GoalKind.COMMITMENT_PREPARE_DAY:
            message = (
                f"Prepared today's operational brief with "
                f"{len(brief.commitments)} commitments, "
                f"{brief.urgent_count} urgent items, "
                f"{brief.responses_needed} responses needed, and "
                f"{len(brief.conflicts)} calendar conflicts. "
                "Focus blocks are proposals only; no external system changed."
            )
        elif goal is GoalKind.COMMITMENT_LIST:
            lines = [
                f"- [{item.priority.value}] {item.summary}"
                + (
                    f" — due {item.due_at.isoformat()}"
                    if item.due_at
                    else ""
                )
                for item in brief.commitments[:20]
            ]
            message = (
                "Open commitments:\n"
                + (
                    "\n".join(lines)
                    if lines
                    else "No evidence-backed commitments were found."
                )
                + "\n\nNo external write was performed."
            )
        elif goal is GoalKind.COMMUNICATION_NEEDS_REPLY:
            items = [
                item
                for item in brief.commitments
                if item.response_needed
            ]
            lines = [
                f"- {item.summary} — {item.counterparty or 'unknown'}"
                for item in items[:20]
            ]
            message = (
                "Communications needing a response:\n"
                + (
                    "\n".join(lines)
                    if lines
                    else "No response-needed item was found."
                )
                + "\n\nNo reply was sent."
            )
        elif goal is GoalKind.CALENDAR_CONFLICTS:
            lines = [
                f"- {item.first_title} overlaps {item.second_title} "
                f"for {item.minutes} minutes"
                for item in brief.conflicts
            ]
            message = (
                "Calendar conflicts:\n"
                + (
                    "\n".join(lines)
                    if lines
                    else "No overlapping events were detected."
                )
                + "\n\nNo calendar event was modified."
            )
        else:
            raise CommitmentGoalExecutionError(
                "COMMITMENT_GOAL_UNSUPPORTED",
                "This commitment goal is not read-only.",
            )

        return self._result(goal.value, message, data)

    @staticmethod
    def _result(
        operation: str,
        message: str,
        data: dict[str, object],
    ) -> GoalExecutionResult:
        digest = hashlib.sha256(
            json.dumps(
                data,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return GoalExecutionResult(
            operation=operation,
            assistant_message=message,
            data=data,
            evidence_sha256=digest,
        )

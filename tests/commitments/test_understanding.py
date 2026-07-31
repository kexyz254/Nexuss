from uuid import uuid4

from nexuss.commitments.models import (
    CommitmentHealth,
    PrepareDayRequest,
    WorkdayBrief,
)
from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.commitment_executor import CommitmentGoalExecutor
from nexuss.understanding.models import (
    GoalKind,
    ResolutionStatus,
    UnderstandingRequest,
)
from nexuss.understanding.service import GoalUnderstandingService


class CommitmentStub:
    def health(self):
        return CommitmentHealth(
            google_workspace_connected=False,
            trusted_mobile_feed_available=True,
        )

    def prepare_day(self, request: PrepareDayRequest):
        return WorkdayBrief(
            planning_date=request.planning_date,
            timezone=request.timezone,
            connected_google_account=None,
            source_status={
                "gmail": False,
                "calendar": False,
                "contacts": False,
                "mobile": True,
            },
            commitments=(),
            calendar_events=(),
            conflicts=(),
            focus_blocks=(),
            urgent_count=0,
            overdue_count=0,
            responses_needed=0,
        )


def test_classifier_routes_prepare_day() -> None:
    result = GoalClassifier().classify("Prepare my day. Read only.")
    assert result.goal is GoalKind.COMMITMENT_PREPARE_DAY


def test_understanding_executes_safe_commitment_read() -> None:
    service = GoalUnderstandingService(
        commitment_executor=CommitmentGoalExecutor(CommitmentStub())
    )
    response = service.resolve(
        UnderstandingRequest(utterance="Prepare my day. Read only."),
        session_id=uuid4(),
    )
    assert response.status is ResolutionStatus.COMPLETED
    assert response.execution is not None


def test_external_communication_write_is_blocked() -> None:
    service = GoalUnderstandingService(
        commitment_executor=CommitmentGoalExecutor(CommitmentStub())
    )
    response = service.resolve(
        UnderstandingRequest(
            utterance="Send email to Sarah without approval."
        ),
        session_id=uuid4(),
    )
    assert response.status is ResolutionStatus.BLOCKED
    assert response.no_action_performed is True

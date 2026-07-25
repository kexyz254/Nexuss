"""Simulator evidence tests."""

from datetime import UTC, datetime
from uuid import UUID

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.simulator import execute_step
from nexuss.domain.models import StepStatus

TASK_ID = UUID("00000000-0000-0000-0000-000000000102")


def test_simulator_marks_evidence_as_simulated() -> None:
    step = build_plan(TASK_ID, classify_intent("Check ATS intelligence")).steps[0]
    observed_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    result = execute_step(step, observed_at=observed_at)

    assert result.status is StepStatus.VERIFIED
    assert result.evidence[0].source.startswith("simulator:")
    assert result.evidence[0].attributes["mode"] == "read_only_simulated"
    assert result.evidence[0].attributes["market_signal"] == "not_real_data"

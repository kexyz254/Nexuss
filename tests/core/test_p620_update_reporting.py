from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexuss.core.executor import _execute_update_inspect
from nexuss.domain.models import PlanStep, RiskTier
from nexuss.local_control.models import LocalUpdateStatus


class _FakeLocalControl:
    def __init__(self, status: LocalUpdateStatus) -> None:
        self._status = status

    def inspect_update(self) -> LocalUpdateStatus:
        return self._status


def _step() -> PlanStep:
    return PlanStep(
        step_id=uuid4(),
        order=1,
        capability_id="system.update.inspect",
        risk_tier=RiskTier.LOW,
        expected_evidence=["local_update_status"],
        parameters={},
        reversible=False,
    )


def test_update_check_reports_up_to_date_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = LocalUpdateStatus(
        branch="feature/p5-knowledge-media-mobile",
        current_sha="a" * 40,
        remote_sha="a" * 40,
        clean_worktree=True,
        fast_forward_available=True,
        update_available=False,
        ahead_by=0,
        behind_by=0,
        restart_required=False,
    )
    monkeypatch.setattr(
        "nexuss.core.executor.HttpLocalControlClient.from_environment",
        lambda: _FakeLocalControl(status),
    )

    result = _execute_update_inspect(_step(), datetime.now(UTC))
    display = result.evidence[0].attributes["display_text"]

    assert "up to date" in display
    assert status.current_sha[:12] in display


def test_update_check_reports_actionable_fast_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = LocalUpdateStatus(
        branch="feature/p5-knowledge-media-mobile",
        current_sha="a" * 40,
        remote_sha="b" * 40,
        clean_worktree=True,
        fast_forward_available=True,
        update_available=True,
        ahead_by=0,
        behind_by=4,
        restart_required=True,
    )
    monkeypatch.setattr(
        "nexuss.core.executor.HttpLocalControlClient.from_environment",
        lambda: _FakeLocalControl(status),
    )

    result = _execute_update_inspect(_step(), None)
    display = result.evidence[0].attributes["display_text"]

    assert "update is available" in display
    assert "Update Nexuss" in display
    assert status.remote_sha[:12] in display

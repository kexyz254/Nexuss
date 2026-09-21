from __future__ import annotations

from nexuss.conversation.stabilization import deterministic_route_result
from nexuss.interactions.service import _is_lifecycle_followup


def test_update_check_is_deterministic_action() -> None:
    result = deterministic_route_result("Check for Nexuss updates.")
    assert result is not None
    assert result.classification.route.value == "action"
    assert result.classification.capability_hint == "system.update.inspect"
    assert result.classification.action_instruction == "Check for Nexuss updates."
    assert result.source == "deterministic_update_check"


def test_update_result_is_deterministic_action() -> None:
    result = deterministic_route_result("Did the Nexuss update succeed?")
    assert result is not None
    assert result.classification.route.value == "action"
    assert result.classification.capability_hint == "system.update.result"
    assert result.source == "deterministic_update_result"


def test_short_followups_bind_to_governed_lifecycle() -> None:
    assert _is_lifecycle_followup("Did it work?")
    assert _is_lifecycle_followup("What happened?")
    assert _is_lifecycle_followup("Is it done?")
    assert _is_lifecycle_followup("What was the result?")
    assert not _is_lifecycle_followup("What is reinforcement learning?")

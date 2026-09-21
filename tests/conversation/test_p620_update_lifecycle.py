from __future__ import annotations

from nexuss.conversation.models import ConversationRoute
from nexuss.conversation.stabilization import deterministic_route_result
from nexuss.interactions.service import _is_lifecycle_followup


def test_update_check_bypasses_provider_chat() -> None:
    result = deterministic_route_result("Check for Nexuss updates.")
    assert result is not None
    classification = result.classification
    assert classification.route is ConversationRoute.ACTION
    assert classification.capability_hint == "system.update.inspect"
    assert classification.action_instruction == "Check for Nexuss updates."
    assert result.source == "deterministic_update_check"


def test_update_result_bypasses_provider_chat() -> None:
    result = deterministic_route_result("Did the Nexuss update succeed?")
    assert result is not None
    classification = result.classification
    assert classification.route is ConversationRoute.ACTION
    assert classification.capability_hint == "system.update.result"
    assert classification.action_instruction == "Did the Nexuss update succeed?"
    assert result.source == "deterministic_update_result"


def test_update_apply_is_distinct_from_self_build() -> None:
    result = deterministic_route_result("Update Nexuss.")
    assert result is not None
    classification = result.classification
    assert classification.route is ConversationRoute.ACTION
    assert classification.capability_hint == "system.update.apply"
    assert classification.action_instruction == "Update Nexuss."
    assert result.source == "deterministic_update_apply"


def test_generic_followup_phrases_bind_to_lifecycle() -> None:
    for utterance in (
        "Did it work?",
        "Did that succeed?",
        "Is it done?",
        "What happened?",
        "What was the result?",
        "How did that go?",
        "Show the status",
    ):
        assert _is_lifecycle_followup(utterance) is True

    assert _is_lifecycle_followup("Explain how Git works.") is False

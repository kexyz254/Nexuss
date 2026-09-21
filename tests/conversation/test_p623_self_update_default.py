from __future__ import annotations

import pytest

from nexuss.conversation.models import ConversationRoute
from nexuss.conversation.stabilization import deterministic_route_result
from nexuss.core.intents import classify_intent
from nexuss.domain.models import IntentKind


@pytest.mark.parametrize(
    "utterance",
    (
        "check for updates",
        "Check for updates.",
        "check updates",
        "update status",
        "any updates?",
        "are there any updates?",
        "please check for updates",
    ),
)
def test_unqualified_update_check_defaults_to_nexuss(
    utterance: str,
) -> None:
    result = deterministic_route_result(utterance)

    assert result is not None
    assert result.classification.route is ConversationRoute.ACTION
    assert result.classification.capability_hint == "system.update.inspect"
    assert (
        result.classification.action_instruction
        == "Check for Nexuss updates."
    )
    assert result.source == "deterministic_update_check"

    intent = classify_intent(utterance)
    assert intent.kind is IntentKind.SYSTEM_UPDATE_STATUS


@pytest.mark.parametrize(
    "utterance",
    (
        "check for updates on TAS",
        "check Python updates",
        "any updates on my project?",
        "check for market updates",
    ),
)
def test_named_update_subject_is_not_hijacked_as_nexuss_update(
    utterance: str,
) -> None:
    result = deterministic_route_result(utterance)

    assert (
        result is None
        or result.classification.capability_hint != "system.update.inspect"
    )
    assert classify_intent(utterance).kind is not IntentKind.SYSTEM_UPDATE_STATUS

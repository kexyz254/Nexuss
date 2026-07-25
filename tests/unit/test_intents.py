"""Deterministic intent-classifier and entity-extraction tests."""

import pytest

from nexuss.core.intents import classify_intent
from nexuss.domain.models import IntentKind


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("Who are you?", IntentKind.ASSISTANT_IDENTITY),
        ("What can you do?", IntentKind.ASSISTANT_CAPABILITIES),
        ("Help", IntentKind.ASSISTANT_HELP),
        ("Give me my daily briefing", IntentKind.DAILY_BRIEFING),
        ("Check ATS intelligence", IntentKind.ATS_READ),
        ("Check system health", IntentKind.SYSTEM_HEALTH),
        ("Play a music video", IntentKind.PLAY_MEDIA),
        ("Prepare my workspace", IntentKind.PREPARE_WORKSPACE),
        ("ATS buy BTC", IntentKind.ATS_WRITE),
        ("Send money using M-Pesa", IntentKind.FINANCIAL_TRANSFER),
        ("Post on Facebook", IntentKind.SOCIAL_PUBLISH),
        ("Do something undefined", IntentKind.UNKNOWN),
    ],
)
def test_intent_classification(utterance: str, expected: IntentKind) -> None:
    assert classify_intent(utterance).kind is expected


def test_create_note_extracts_title_and_checklist() -> None:
    intent = classify_intent(
        "Create a note called Nexuss launch checklist with the tasks: verify P3, "
        "review the Action Receipt, and test undo."
    )

    assert intent.kind is IntentKind.CREATE_NOTE
    assert intent.entities["title"] == "Nexuss launch checklist"
    assert intent.entities["content"] == (
        "# Nexuss launch checklist\n\n"
        "- [ ] verify P3\n"
        "- [ ] review the Action Receipt\n"
        "- [ ] test undo\n"
    )

"""Deterministic intent-classifier tests."""

import pytest

from nexuss.core.intents import classify_intent
from nexuss.domain.models import IntentKind


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
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

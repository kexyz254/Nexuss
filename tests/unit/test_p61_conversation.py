"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Conversational basics and the imperative/question boundary.

The boundary matters beyond tidiness: a false positive sends an unmatched
instruction to a public source, so the classifier fails towards "no capability
matched" rather than towards searching the web.
"""

import pytest

from nexuss.core.intents import classify_intent
from nexuss.domain.models import IntentKind


@pytest.mark.parametrize(
    "utterance",
    [
        "hello",
        "hello there",
        "Hi",
        "hey",
        "good morning",
        "thanks",
        "thank you",
        "bye",
        "good night",
        "how are you",
    ],
)
def test_courtesies_are_answered_not_denied(utterance: str) -> None:
    """A greeting reaching nexuss.unsupported is denied at HIGH risk, which
    treats "hello" as an attempted escalation."""
    assert classify_intent(utterance).kind is IntentKind.SMALL_TALK


@pytest.mark.parametrize(
    "utterance",
    ["hide the panel", "history of forex", "highlight that result", "later stages of the plan"],
)
def test_courtesy_matching_does_not_fire_inside_longer_words(utterance: str) -> None:
    assert classify_intent(utterance).kind is not IntentKind.SMALL_TALK


@pytest.mark.parametrize(
    ("utterance", "field"),
    [
        ("what time is it", "time"),
        ("what's the time", "time"),
        ("what is the date", "date"),
        ("what day is it", "date"),
    ],
)
def test_clock_questions_are_answered_from_the_system_clock(utterance: str, field: str) -> None:
    intent = classify_intent(utterance)

    assert intent.kind is IntentKind.DATETIME_QUERY
    assert intent.entities["datetime_field"] == field


@pytest.mark.parametrize(
    "utterance",
    [
        "what is a limit order",
        "who won the match",
        "why did that fail",
        "do you know what a limit order is",
        "does it support markdown",
        "should I use a limit order",
        "is my phone paired",
        "tell me about forex",
        "explain limit orders",
        "define slippage",
        "something odd?",
    ],
)
def test_questions_become_open_questions(utterance: str) -> None:
    assert classify_intent(utterance).kind is IntentKind.OPEN_QUESTION


@pytest.mark.parametrize(
    "utterance",
    [
        "Do something undefined",
        "do something",
        "close media",
        "open the panel",
        "delete that note",
        "make it bigger",
    ],
)
def test_imperatives_never_reach_a_public_source(utterance: str) -> None:
    """An auxiliary verb opens a question only when a subject follows.
    "do you know" is a question; "do something" is a command."""
    assert classify_intent(utterance).kind is not IntentKind.OPEN_QUESTION


def test_a_research_request_stays_with_the_research_capability() -> None:
    """Precedence check: "can you research forex" is question-shaped, but a
    registered capability already handles it and must keep it."""
    assert classify_intent("can you research forex").kind is not IntentKind.OPEN_QUESTION


def test_an_open_question_carries_the_original_wording() -> None:
    intent = classify_intent("what is a limit order")

    assert intent.entities["question"] == "what is a limit order"

"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from nexuss.core.intents import classify_intent
from nexuss.domain.models import IntentKind


def test_research_intent_extracts_query() -> None:
    intent = classify_intent("Google knowledge about forex")
    assert intent.kind is IntentKind.WEB_RESEARCH
    assert intent.entities["query"] == "forex"

    detailed = classify_intent(
        "Research the fundamentals of forex and prepare a cited beginner brief."
    )
    assert detailed.kind is IntentKind.WEB_RESEARCH
    assert detailed.entities["query"] == "the fundamentals of forex"


def test_media_intent_preserves_exact_title_and_artist() -> None:
    intent = classify_intent("Play Silence by Popcaan.")

    assert intent.kind is IntentKind.YOUTUBE_SEARCH
    assert intent.entities == {
        "query": "Silence by Popcaan",
        "provider": "youtube",
        "media_title": "Silence",
        "media_artist": "Popcaan",
    }
    assert intent.confidence == 0.98


def test_media_intent_handles_politeness_punctuation_and_bounded_typos() -> None:
    prompts = (
        "*lay Silence by Popcaan",
        "Please play Silence by Popcaan",
        "Paly Silence by Popcaan",
        "Search YouTube for Silence by Popcaan",
        "Open YouTube and search for Silence by Popcaan",
        "Nexuss, watch Popcaan - Silence",
    )

    for prompt in prompts:
        intent = classify_intent(prompt)
        assert intent.kind is IntentKind.YOUTUBE_SEARCH, prompt
        assert "silence" in intent.entities["query"].casefold(), prompt
        assert "popcaan" in intent.entities["query"].casefold(), prompt


def test_phone_youtube_intent_preserves_query_and_requires_no_rewrite() -> None:
    phone = classify_intent(
        "Open YouTube on my phone and search Silence by Popcaan"
    )

    assert phone.kind is IntentKind.PHONE_OPEN_YOUTUBE
    assert phone.entities["query"] == "Silence by Popcaan"
    assert phone.entities["media_title"] == "Silence"
    assert phone.entities["media_artist"] == "Popcaan"


def test_unrelated_text_remains_unknown() -> None:
    intent = classify_intent("Lay the documents on the table")
    assert intent.kind is IntentKind.UNKNOWN

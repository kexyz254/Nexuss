"""Deterministic intent classification for the Nexuss P2 vertical slice."""

from nexuss.domain.models import Intent, IntentKind


def classify_intent(utterance: str) -> Intent:
    normalized = " ".join(utterance.casefold().split())

    if any(term in normalized for term in ("send money", "transfer money", "m-pesa")):
        kind = IntentKind.FINANCIAL_TRANSFER
        confidence = 0.99
    elif any(term in normalized for term in ("publish", "post on facebook", "social post")):
        kind = IntentKind.SOCIAL_PUBLISH
        confidence = 0.98
    elif "ats" in normalized and any(
        term in normalized for term in ("buy", "sell", "trade", "place order", "write")
    ):
        kind = IntentKind.ATS_WRITE
        confidence = 0.99
    elif any(
        term in normalized for term in ("workspace", "repository", "repo", "computer")
    ) and any(term in normalized for term in ("status", "check", "inspect", "system")):
        kind = IntentKind.LOCAL_WORKSPACE_STATUS
        confidence = 0.98
    elif "daily briefing" in normalized or normalized == "briefing":
        kind = IntentKind.DAILY_BRIEFING
        confidence = 0.99
    elif "prepare" in normalized and "workspace" in normalized:
        kind = IntentKind.PREPARE_WORKSPACE
        confidence = 0.97
    elif "ats" in normalized:
        kind = IntentKind.ATS_READ
        confidence = 0.96
    elif "health" in normalized:
        kind = IntentKind.SYSTEM_HEALTH
        confidence = 0.95
    elif "play" in normalized and any(
        term in normalized for term in ("media", "music", "song", "video")
    ):
        kind = IntentKind.PLAY_MEDIA
        confidence = 0.94
    else:
        kind = IntentKind.UNKNOWN
        confidence = 0.0

    return Intent(
        kind=kind,
        normalized_text=normalized,
        confidence=confidence,
        entities={},
    )

"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Deterministic intent classification and bounded entity extraction for Nexuss P4.
"""

from __future__ import annotations

import re

from nexuss.domain.models import Intent, IntentKind

_NOTE_PATTERN = re.compile(
    r"^(?:please\s+)?(?:create|make|write|save)\s+(?:a\s+)?note"
    r"(?:\s+(?:called|titled|named)\s+)(?P<title>.+?)"
    r"(?:\s+(?:with(?:\s+the)?\s+(?:tasks?|content)\s*:?|containing|that\s+says)\s+"
    r"(?P<body>.+))?$",
    re.IGNORECASE,
)


def _format_note_content(title: str, body: str | None) -> str:
    heading = f"# {title.strip()}"
    if body is None or not body.strip():
        return f"{heading}\n\nCreated with Nexuss.\n"

    normalized_body = body.strip().rstrip(".")
    task_prefix = re.match(r"^(?:the\s+)?tasks?\s*:\s*(.+)$", normalized_body, re.IGNORECASE)
    if task_prefix:
        normalized_body = task_prefix.group(1).strip()

    raw_items = re.split(r"\s*,\s*|\s+and\s+", normalized_body)
    items = [
        re.sub(r"^(?:and|or)\s+", "", item.strip(" ."), flags=re.IGNORECASE)
        for item in raw_items
        if item.strip(" .")
    ]
    if len(items) >= 2:
        checklist = "\n".join(f"- [ ] {item}" for item in items)
        return f"{heading}\n\n{checklist}\n"
    return f"{heading}\n\n{normalized_body}\n"


def classify_intent(utterance: str) -> Intent:
    normalized = " ".join(utterance.casefold().split())
    note_match = _NOTE_PATTERN.match(utterance.strip())

    entities: dict[str, str] = {}
    if note_match:
        raw_title = note_match.group("title").strip(" \"'")
        raw_body = note_match.group("body")
        entities = {
            "title": raw_title,
            "content": _format_note_content(raw_title, raw_body),
        }
        kind = IntentKind.CREATE_NOTE
        confidence = 0.99
    elif any(term in normalized for term in ("who are you", "what are you", "introduce yourself")):
        kind = IntentKind.ASSISTANT_IDENTITY
        confidence = 0.99
    elif any(
        term in normalized
        for term in ("what can you do", "your capabilities", "show capabilities")
    ):
        kind = IntentKind.ASSISTANT_CAPABILITIES
        confidence = 0.98
    elif (
        normalized in {"help", "help me", "how do i use nexuss"}
        or "how can you help" in normalized
    ):
        kind = IntentKind.ASSISTANT_HELP
        confidence = 0.97
    elif any(
        phrase in normalized
        for phrase in (
            "open notepad",
            "launch notepad",
            "start notepad",
            "open text editor",
        )
    ):
        kind = IntentKind.LAUNCH_NOTEPAD
        confidence = 0.99
        entities = {"target_node_id": "windows-primary"}
    elif any(term in normalized for term in ("send money", "transfer money", "m-pesa")):
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
        entities=entities,
    )

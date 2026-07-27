"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Deterministic, context-aware intent classification for Nexuss P5.1.
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

_RESEARCH_PREFIXES = (
    "google knowledge about",
    "research",
    "learn about",
    "knowledge about",
)

_PHONE_YOUTUBE_PATTERNS = (
    re.compile(
        r"^open\s+youtube\s+on\s+(?:my\s+)?(?:phone|mobile)"
        r"(?:\s+(?:and\s+)?search(?:\s+for)?\s+)?(?P<query>.*)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:search|find)\s+youtube\s+on\s+(?:my\s+)?(?:phone|mobile)"
        r"(?:\s+for)?\s+(?P<query>.+)$",
        re.IGNORECASE,
    ),
)

_DESKTOP_YOUTUBE_PATTERNS = (
    re.compile(
        r"^open\s+youtube(?:\s+(?:and\s+)?search(?:\s+for)?\s+)?(?P<query>.*)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:search|find)\s+(?:on\s+)?youtube(?:\s+for)?\s+(?P<query>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^youtube(?:\s+search(?:\s+for)?)?\s+(?P<query>.+)$", re.IGNORECASE),
    re.compile(
        r"^(?:play|watch|stream|put\s+on|listen\s+to)\s+"
        r"(?:youtube\s+)?(?P<query>.+)$",
        re.IGNORECASE,
    ),
)

_WEB_SEARCH_PREFIXES = (
    "open chrome and search",
    "open chrome to search",
    "google",
    "search",
)

_POLITE_PREFIXES = (
    "nexuss ",
    "please ",
    "please can you ",
    "can you please ",
    "can you ",
    "could you please ",
    "could you ",
    "would you please ",
    "would you ",
    "i want you to ",
    "i would like you to ",
)

_COMMAND_WORDS = ("play", "watch", "search", "open")


def _format_note_content(title: str, body: str | None) -> str:
    heading = f"# {title.strip()}"
    if body is None or not body.strip():
        return f"{heading}\n\nCreated with Nexuss.\n"

    normalized_body = body.strip().rstrip(".")
    task_prefix = re.match(
        r"^(?:the\s+)?tasks?\s*:\s*(.+)$",
        normalized_body,
        re.IGNORECASE,
    )
    if task_prefix:
        normalized_body = task_prefix.group(1).strip()

    raw_items = re.split(r"\s*,\s*|\s+and\s+", normalized_body)
    items = [
        re.sub(
            r"^(?:and|or)\s+",
            "",
            item.strip(" ."),
            flags=re.IGNORECASE,
        )
        for item in raw_items
        if item.strip(" .")
    ]
    if len(items) >= 2:
        checklist = "\n".join(f"- [ ] {item}" for item in items)
        return f"{heading}\n\n{checklist}\n"
    return f"{heading}\n\n{normalized_body}\n"


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False

    if len(left) == len(right):
        differing = [
            index
            for index, (a, b) in enumerate(zip(left, right, strict=True))
            if a != b
        ]
        if len(differing) <= 1:
            return True
        if len(differing) == 2:
            first, second = differing
            return (
                second == first + 1
                and left[first] == right[second]
                and left[second] == right[first]
            )
        return False

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = 0
    long_index = 0
    skipped = False
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        if skipped:
            return False
        skipped = True
        long_index += 1
    return True


def _strip_leading_noise(value: str) -> str:
    cleaned = value.strip().lstrip("*#>-:;,.!?•·_ ")
    cleaned = re.sub(
        r"^nexuss\s*[,;:-]?\s+",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    )
    lowered = cleaned.casefold()
    changed = True
    while changed:
        changed = False
        for prefix in _POLITE_PREFIXES:
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix) :].lstrip()
                lowered = cleaned.casefold()
                changed = True
                break

    first, separator, remainder = cleaned.partition(" ")
    media_signal = any(
        signal in remainder.casefold()
        for signal in ("youtube", "video", "song", "music", " by ", " - ")
    )
    if separator and media_signal and first.casefold() not in _COMMAND_WORDS:
        matches = [
            command
            for command in _COMMAND_WORDS
            if _edit_distance_at_most_one(first.casefold(), command)
        ]
        if len(matches) == 1:
            cleaned = f"{matches[0]} {remainder}"
    return " ".join(cleaned.split())


def _extract_query(normalized: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix).strip(" :.-")
    return normalized.strip(" :.-")


def _research_query(normalized: str) -> str:
    query = _extract_query(normalized, _RESEARCH_PREFIXES)
    for separator in (
        " and prepare ",
        " then prepare ",
        " and create ",
        " then create ",
        " and write ",
        " then write ",
    ):
        if separator in query:
            query = query.split(separator, maxsplit=1)[0]
            break
    return query.strip(" :.-")


def _match_query(value: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for pattern in patterns:
        match = pattern.match(value)
        if match:
            return match.group("query").strip(" :.-")
    return None


def _media_entities(query: str) -> dict[str, str]:
    entities = {"query": query, "provider": "youtube"}
    by_match = re.match(
        r"^(?P<title>.+?)\s+by\s+(?P<artist>.+)$",
        query,
        re.IGNORECASE,
    )
    dash_match = re.match(r"^(?P<artist>.+?)\s+-\s+(?P<title>.+)$", query)
    match = by_match or dash_match
    if match:
        entities["media_title"] = match.group("title").strip(" \"'")
        entities["media_artist"] = match.group("artist").strip(" \"'")

    lowered = query.casefold()
    for version in ("official video", "official audio", "lyrics", "live", "remix"):
        if version in lowered:
            entities["media_version"] = version
            break
    return entities


# Device-pairing vocabulary. "unpair my phone" contains "pair my phone", so
# the unpair check must always run first.
def _device_phrases(verbs: tuple[str, ...]) -> tuple[str, ...]:
    """Expand verb x determiner x noun so no combination is left out.

    Hand-written lists of these reliably miss a case; the first version of
    this table omitted "forget this device".
    """
    return tuple(
        f"{verb} {determiner} {noun}".replace("  ", " ").strip()
        for verb in verbs
        for determiner in ("my", "this", "the", "")
        for noun in ("phone", "device")
    )


# Device-pairing vocabulary. "unpair my phone" contains "pair my phone", so
# the unpair check must always run before the pair check.
#
# These verbs mean only one thing, so they carry any label: "unpair Galaxy S24".
_UNAMBIGUOUS_UNPAIR_VERBS = ("unpair", "untrust", "unlink")

# These verbs are ambiguous on their own, so they require the word phone or
# device. "remove the Galaxy S24" should not be read as a revocation.
_UNPAIR_PHONE_TERMS = _device_phrases(
    ("forget", "remove", "revoke", "disconnect", "unlink", "untrust", "unpair")
)


def _is_unpair_request(normalized: str) -> bool:
    if normalized.startswith(_UNAMBIGUOUS_UNPAIR_VERBS):
        return True
    return _contains_any(normalized, _UNPAIR_PHONE_TERMS)

_LIST_DEVICE_TERMS = (
    "list my devices",
    "list devices",
    "list my phones",
    "list phones",
    "list paired",
    "show my devices",
    "show devices",
    "show my phones",
    "show paired",
    "paired devices",
    "paired phones",
    "which phones are paired",
    "which devices are paired",
    "what devices are paired",
)

_PAIR_PHONE_TERMS = _device_phrases(
    ("pair", "add", "connect", "link", "register", "trust", "set up")
) + (
    "pair a phone",
    "pair a device",
    "pair a new phone",
    "pair a new device",
    "add a phone",
    "add a device",
    "add a new phone",
    "add a new device",
    "connect a phone",
    "connect a device",
)

_UNPAIR_VERB_PATTERN = re.compile(
    r"(?:unpair|remove|forget|revoke|disconnect|unlink|untrust)\s+(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)

_DETERMINERS = ("the ", "my ", "this ", "that ")
_BARE_DEVICE_WORDS = frozenset({"phone", "device", "it", "this", "that"})


def _unpair_label(display_text: str) -> str:
    """Extract a device label when one was named.

    Deliberately does not consume a leading "phone"/"device" token inside the
    regex. Matching is case-insensitive, so an optional noun group swallows
    the first word of a real label: "unpair Phone A" yielded "A".

    An empty result means "the only paired device", which the executor
    resolves. It refuses rather than guessing when several are paired.
    """
    match = _UNPAIR_VERB_PATTERN.search(display_text)
    if match is None:
        return ""

    remainder = match.group("rest").strip(" \"'")
    lowered = remainder.casefold()
    for determiner in _DETERMINERS:
        if lowered.startswith(determiner):
            remainder = remainder[len(determiner):].strip(" \"'")
            break

    if remainder.casefold() in _BARE_DEVICE_WORDS:
        return ""
    return remainder


# Memory vocabulary. "forget about <topic>" requires the word "about" so it
# can never collide with device revocation ("forget this device"), which is
# classified earlier and requires a device noun.
_REMEMBER_PATTERN = re.compile(
    r"^(?:remember|memori[sz]e)\s+(?:that\s+)?(?P<statement>.+?)\s*$",
    re.IGNORECASE,
)

_RECALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^what\s+do\s+you\s+remember\s+about\s+(?P<query>.+?)\s*$", re.IGNORECASE),
    re.compile(r"^what\s+have\s+you\s+learn(?:ed|t)\s+about\s+(?P<query>.+?)\s*$", re.IGNORECASE),
    re.compile(r"^recall\s+(?P<query>.+?)\s*$", re.IGNORECASE),
)

_FORGET_MEMORY_PATTERN = re.compile(
    r"^forget\s+(?:everything\s+|what\s+you\s+know\s+)?about\s+(?P<topic>.+?)\s*$",
    re.IGNORECASE,
)


def _match_memory(display_text: str) -> tuple[IntentKind, dict[str, str]] | None:
    forget = _FORGET_MEMORY_PATTERN.match(display_text)
    if forget:
        return IntentKind.MEMORY_FORGET, {"topic": forget.group("topic").strip(" \"'")}
    for pattern in _RECALL_PATTERNS:
        recall = pattern.match(display_text)
        if recall:
            return IntentKind.MEMORY_RECALL, {"query": recall.group("query").strip(" \"'")}
    remember = _REMEMBER_PATTERN.match(display_text)
    if remember:
        return IntentKind.MEMORY_REMEMBER, {
            "statement": remember.group("statement").strip(" \"'")
        }
    return None


def classify_intent(utterance: str) -> Intent:
    display_text = _strip_leading_noise(utterance)
    normalized = display_text.casefold()
    note_match = _NOTE_PATTERN.match(display_text)
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
    elif _contains_any(
        normalized,
        ("who are you", "what are you", "introduce yourself"),
    ):
        kind = IntentKind.ASSISTANT_IDENTITY
        confidence = 0.99
    elif _contains_any(
        normalized,
        ("what can you do", "your capabilities", "show capabilities"),
    ):
        kind = IntentKind.ASSISTANT_CAPABILITIES
        confidence = 0.98
    elif (
        normalized in {"help", "help me", "how do i use nexuss"}
        or "how can you help" in normalized
    ):
        kind = IntentKind.ASSISTANT_HELP
        confidence = 0.97
    elif (memory_match := _match_memory(display_text)) is not None:
        kind, entities = memory_match
        confidence = 0.98
    elif _is_unpair_request(normalized):
        kind = IntentKind.UNPAIR_PHONE
        confidence = 0.97
        entities = {"device_label": _unpair_label(display_text)}
    elif _contains_any(normalized, _LIST_DEVICE_TERMS):
        kind = IntentKind.LIST_PAIRED_DEVICES
        confidence = 0.97
    elif _contains_any(normalized, _PAIR_PHONE_TERMS):
        kind = IntentKind.PAIR_PHONE
        confidence = 0.98
    elif (phone_query := _match_query(display_text, _PHONE_YOUTUBE_PATTERNS)) is not None:
        kind = IntentKind.PHONE_OPEN_YOUTUBE
        confidence = 0.99
        entities = _media_entities(phone_query or "YouTube")
    elif _contains_any(
        normalized,
        (
            "research ",
            "learn about ",
            "knowledge about ",
            "google knowledge about ",
        ),
    ):
        query = _research_query(normalized)
        kind = IntentKind.WEB_RESEARCH
        confidence = 0.97
        entities = {"query": query}
    elif normalized in {
        "play a music video",
        "play media",
        "play music",
        "play a video",
    }:
        kind = IntentKind.PLAY_MEDIA
        confidence = 0.94
    elif (media_query := _match_query(display_text, _DESKTOP_YOUTUBE_PATTERNS)) is not None:
        kind = IntentKind.YOUTUBE_SEARCH
        confidence = 0.98
        entities = _media_entities(media_query)
    elif (
        "chrome" in normalized or "browser" in normalized
    ) and _contains_any(normalized, ("search", "google", "open")):
        query = _extract_query(normalized, _WEB_SEARCH_PREFIXES)
        kind = IntentKind.OPEN_WEB_SEARCH
        confidence = 0.96
        entities = {"query": query or "Nexuss", "provider": "google"}
    elif _contains_any(
        normalized,
        ("open notepad", "launch notepad", "start notepad", "open text editor"),
    ):
        kind = IntentKind.LAUNCH_NOTEPAD
        confidence = 0.99
        entities = {"target_node_id": "windows-primary"}
    elif _contains_any(normalized, ("send money", "transfer money", "m-pesa")):
        kind = IntentKind.FINANCIAL_TRANSFER
        confidence = 0.99
    elif _contains_any(normalized, ("publish", "post on facebook", "social post")):
        kind = IntentKind.SOCIAL_PUBLISH
        confidence = 0.98
    elif "ats" in normalized and _contains_any(
        normalized,
        ("buy", "sell", "trade", "place order", "write"),
    ):
        kind = IntentKind.ATS_WRITE
        confidence = 0.99
    elif _contains_any(
        normalized,
        ("workspace", "repository", "repo", "computer"),
    ) and _contains_any(normalized, ("status", "check", "inspect", "system")):
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
    elif "play" in normalized and _contains_any(
        normalized,
        ("media", "music", "song", "video"),
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

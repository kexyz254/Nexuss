"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from __future__ import annotations

from urllib.parse import quote_plus, urlparse


class WebActionValidationError(ValueError):
    """Raised when a browser or phone handoff URL leaves the allowlist."""


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split()).strip()
    if not normalized or len(normalized) > 240:
        raise WebActionValidationError("WEB_QUERY_INVALID")
    return normalized


def google_search_url(query: str) -> str:
    normalized = _normalize_query(query)
    return f"https://www.google.com/search?q={quote_plus(normalized)}"


def youtube_search_url(query: str) -> str:
    normalized = _normalize_query(query)
    return f"https://www.youtube.com/results?search_query={quote_plus(normalized)}"


def _validated_url(value: str, allowed_hosts: set[str]) -> str:
    if len(value) > 2048:
        raise WebActionValidationError("WEB_URL_TOO_LONG")
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise WebActionValidationError("WEB_URL_NOT_ALLOWLISTED")
    if host not in allowed_hosts:
        raise WebActionValidationError("WEB_URL_NOT_ALLOWLISTED")
    return value


def validate_handoff_url(value: str) -> str:
    return _validated_url(
        value,
        {
            "google.com",
            "www.google.com",
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        },
    )


def validate_youtube_handoff_url(value: str) -> str:
    return _validated_url(
        value,
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        },
    )

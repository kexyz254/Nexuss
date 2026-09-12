"""Privacy filtering for stored and provider-visible conversation text."""

from __future__ import annotations

import re
from dataclasses import dataclass


_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_ -]?key|secret|password|access[_ -]?token|"
        r"refresh[_ -]?token|authorization)\b\s*[:=]\s*"
        r"([^\s,;]{6,})"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r".*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class SanitizedText:
    value: str
    redactions: int


def sanitize_text(value: str) -> SanitizedText:
    text = value
    count = 0

    for pattern in _PATTERNS:
        def replacement(match: re.Match[str]) -> str:
            if match.lastindex and match.lastindex >= 2:
                return f"{match.group(1)}=[REDACTED]"
            return "[REDACTED_PRIVATE_KEY]"

        text, substitutions = pattern.subn(replacement, text)
        count += substitutions

    return SanitizedText(value=text, redactions=count)

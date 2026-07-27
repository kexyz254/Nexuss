"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

import pytest

from nexuss.core.web_actions import (
    WebActionValidationError,
    validate_handoff_url,
    validate_youtube_handoff_url,
)


def test_web_handoff_allowlist() -> None:
    assert validate_handoff_url(
        "https://www.youtube.com/results?search_query=forex"
    )
    with pytest.raises(WebActionValidationError):
        validate_handoff_url("https://evil.example/steal")
    with pytest.raises(WebActionValidationError):
        validate_handoff_url("javascript:alert(1)")


def test_youtube_handoff_rejects_non_youtube_hosts() -> None:
    assert validate_youtube_handoff_url(
        "https://www.youtube.com/results?search_query=forex"
    )
    with pytest.raises(WebActionValidationError):
        validate_youtube_handoff_url("https://www.google.com/search?q=forex")


def test_web_handoff_rejects_credentials_and_fragments() -> None:
    with pytest.raises(WebActionValidationError):
        validate_handoff_url(
            "https://user:pass@www.google.com/search?q=forex"
        )
    with pytest.raises(WebActionValidationError):
        validate_handoff_url(
            "https://www.youtube.com/watch?v=M7lc1UVf-VE#fragment"
        )

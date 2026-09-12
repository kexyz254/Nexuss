from datetime import UTC, datetime
from types import SimpleNamespace

from nexuss.interactions.service import _resolve_recent_engineering_continuation


def test_recent_prepared_build_can_be_started_by_short_followup():
    now = datetime.now(UTC)
    messages = (
        SimpleNamespace(
            text=(
                "Here is the task:\n"
                "Nexuss, build yourself: implement P7.1 safely."
            ),
            created_at=now,
        ),
    )
    resolved = _resolve_recent_engineering_continuation(
        "sure create a governed task and make no mistake",
        messages,
        now=now,
    )
    assert resolved == "Nexuss, build yourself: implement P7.1 safely."


def test_negative_continuation_is_not_bound():
    now = datetime.now(UTC)
    messages = (
        SimpleNamespace(
            text="Nexuss, build yourself: implement P7.1 safely.",
            created_at=now,
        ),
    )
    assert _resolve_recent_engineering_continuation(
        "do not continue",
        messages,
        now=now,
    ) is None

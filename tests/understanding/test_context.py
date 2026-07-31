"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Bounded context tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.context import (
    GoalContextRecord,
    GoalContextStore,
    apply_repository_context,
)


def test_pronoun_uses_last_selected_repository() -> None:
    classifier = GoalClassifier()
    interpretation = classifier.classify("Show its open pull requests.")

    resolved = apply_repository_context(
        interpretation,
        "kexyz254/GlyphSentry-Core-Final",
        "main",
    )

    assert resolved.entities.repository_full_name == "kexyz254/GlyphSentry-Core-Final"
    assert resolved.context_used is True
    assert "repository" not in resolved.missing_fields


def test_explicit_repository_overrides_context() -> None:
    classifier = GoalClassifier()
    interpretation = classifier.classify(
        "Analyze kexyz254/Another-Repository."
    )

    resolved = apply_repository_context(
        interpretation,
        "kexyz254/GlyphSentry-Core-Final",
        "main",
    )

    assert resolved.entities.repository_full_name == "kexyz254/Another-Repository"
    assert resolved.context_used is False


def test_context_does_not_apply_without_reference_language() -> None:
    interpretation = GoalClassifier().classify("List open pull requests.")

    resolved = apply_repository_context(
        interpretation,
        "kexyz254/GlyphSentry-Core-Final",
        "main",
    )

    assert resolved.entities.repository_full_name is None


def test_context_store_expires_records() -> None:
    store = GoalContextStore(ttl=timedelta(seconds=1))
    session_id = uuid4()
    interpretation = GoalClassifier().classify(
        "Inspect kexyz254/GlyphSentry-Core-Final."
    )
    store.append(
        session_id,
        GoalContextRecord(
            interpretation=interpretation,
            selected_repository="kexyz254/GlyphSentry-Core-Final",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )

    assert store.recent(
        session_id,
        now=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
    ) == ()

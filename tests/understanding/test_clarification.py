"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Clarification state and authority-boundary tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nexuss.understanding.clarification import (
    ClarificationSessionError,
    ClarificationStore,
)
from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.models import (
    ClarificationKind,
    ClarificationOption,
)


def _store() -> ClarificationStore:
    return ClarificationStore(ttl=timedelta(minutes=5), max_attempts=3)


def test_single_select_answer_is_session_bound() -> None:
    store = _store()
    session_id = uuid4()
    interpretation = GoalClassifier().classify("List open pull requests.")
    question = store.create(
        session_id=session_id,
        request_id=uuid4(),
        interpretation=interpretation,
        kind=ClarificationKind.SINGLE_SELECT,
        question="Which repository?",
        options=(
            ClarificationOption(
                option_id="repo-1",
                label="kexyz254/one",
                value="kexyz254/one",
            ),
            ClarificationOption(
                option_id="repo-2",
                label="kexyz254/two",
                value="kexyz254/two",
            ),
        ),
        field_name="repository",
    )

    pending, option = store.answer(
        question.clarification_id,
        session_id=session_id,
        option_id="repo-1",
    )

    assert pending.session_id == session_id
    assert option.value == "kexyz254/one"


def test_wrong_session_cannot_answer() -> None:
    store = _store()
    session_id = uuid4()
    interpretation = GoalClassifier().classify("Fix it.")
    question = store.create(
        session_id=session_id,
        request_id=uuid4(),
        interpretation=interpretation,
        kind=ClarificationKind.YES_NO,
        question="Did you mean inspect?",
        options=(
            ClarificationOption(option_id="yes", label="Yes", value="yes"),
            ClarificationOption(option_id="no", label="No", value="no"),
        ),
        field_name="confirm_intent",
    )

    with pytest.raises(
        ClarificationSessionError,
        match="CLARIFICATION_SESSION_MISMATCH",
    ):
        store.answer(
            question.clarification_id,
            session_id=uuid4(),
            option_id="yes",
        )


def test_expired_clarification_fails_closed() -> None:
    store = ClarificationStore(ttl=timedelta(seconds=1))
    session_id = uuid4()
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    question = store.create(
        session_id=session_id,
        request_id=uuid4(),
        interpretation=GoalClassifier().classify("Fix it."),
        kind=ClarificationKind.YES_NO,
        question="Did you mean inspect?",
        options=(
            ClarificationOption(option_id="yes", label="Yes", value="yes"),
            ClarificationOption(option_id="no", label="No", value="no"),
        ),
        field_name="confirm_intent",
        now=created_at,
    )

    with pytest.raises(
        ClarificationSessionError,
        match="CLARIFICATION_EXPIRED",
    ):
        store.answer(
            question.clarification_id,
            session_id=session_id,
            option_id="yes",
            now=created_at + timedelta(seconds=2),
        )

"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.


Session-bound clarification state with yes/no and single-select answers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.understanding.models import (
    ClarificationKind,
    ClarificationOption,
    ClarificationQuestion,
    GoalInterpretation,
)


class ClarificationSessionError(ValueError):
    """Raised when clarification state is missing, expired, or session-mismatched."""


class PendingClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clarification_id: UUID
    session_id: UUID
    request_id: UUID
    interpretation: GoalInterpretation
    question: ClarificationQuestion
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    attempts_used: int = Field(default=0, ge=0, le=5)


class ClarificationStore:
    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=10),
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self._ttl = ttl
        self._max_attempts = max_attempts
        self._pending: dict[UUID, PendingClarification] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        interpretation: GoalInterpretation,
        kind: ClarificationKind,
        question: str,
        options: tuple[ClarificationOption, ...],
        field_name: str,
        now: datetime | None = None,
    ) -> ClarificationQuestion:
        created_at = now or datetime.now(UTC)
        expires_at = created_at + self._ttl
        rendered = ClarificationQuestion(
            kind=kind,
            question=question,
            options=options,
            field_name=field_name,
            expires_at=expires_at,
            attempts_remaining=self._max_attempts,
        )
        record = PendingClarification(
            clarification_id=rendered.clarification_id,
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            question=rendered,
            created_at=created_at,
            expires_at=expires_at,
        )
        with self._lock:
            self._pending[rendered.clarification_id] = record
        return rendered

    def answer(
        self,
        clarification_id: UUID,
        *,
        session_id: UUID,
        option_id: str,
        now: datetime | None = None,
    ) -> tuple[PendingClarification, ClarificationOption]:
        checked_at = now or datetime.now(UTC)
        with self._lock:
            record = self._pending.get(clarification_id)
            if record is None:
                raise ClarificationSessionError("CLARIFICATION_NOT_FOUND")
            if record.session_id != session_id:
                raise ClarificationSessionError("CLARIFICATION_SESSION_MISMATCH")
            if record.expires_at <= checked_at:
                self._pending.pop(clarification_id, None)
                raise ClarificationSessionError("CLARIFICATION_EXPIRED")
            if record.attempts_used >= self._max_attempts:
                self._pending.pop(clarification_id, None)
                raise ClarificationSessionError("CLARIFICATION_ATTEMPTS_EXHAUSTED")

            option = next(
                (
                    candidate
                    for candidate in record.question.options
                    if candidate.option_id == option_id
                ),
                None,
            )
            if option is None:
                attempts_used = record.attempts_used + 1
                if attempts_used >= self._max_attempts:
                    self._pending.pop(clarification_id, None)
                else:
                    self._pending[clarification_id] = record.model_copy(
                        update={"attempts_used": attempts_used}
                    )
                raise ClarificationSessionError("CLARIFICATION_OPTION_INVALID")

            self._pending.pop(clarification_id, None)
            return record, option

    def cancel(
        self,
        clarification_id: UUID,
        *,
        session_id: UUID,
    ) -> None:
        with self._lock:
            record = self._pending.get(clarification_id)
            if record is None:
                return
            if record.session_id != session_id:
                raise ClarificationSessionError("CLARIFICATION_SESSION_MISMATCH")
            self._pending.pop(clarification_id, None)

    def get(
        self,
        clarification_id: UUID,
        *,
        session_id: UUID,
        now: datetime | None = None,
    ) -> PendingClarification:
        checked_at = now or datetime.now(UTC)
        with self._lock:
            record = self._pending.get(clarification_id)
            if record is None:
                raise ClarificationSessionError("CLARIFICATION_NOT_FOUND")
            if record.session_id != session_id:
                raise ClarificationSessionError("CLARIFICATION_SESSION_MISMATCH")
            if record.expires_at <= checked_at:
                self._pending.pop(clarification_id, None)
                raise ClarificationSessionError("CLARIFICATION_EXPIRED")
            return record

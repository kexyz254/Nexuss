"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.


Short-lived entity context for safe follow-up resolution.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.understanding.models import (
    GoalInterpretation,
    GoalKind,
    IntentDomain,
    OperationKind,
)


class GoalContextRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interpretation: GoalInterpretation
    selected_repository: str | None = None
    selected_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalContextStore:
    """Bounded session context that never stores or transfers approval."""

    def __init__(
        self,
        *,
        max_records: int = 12,
        ttl: timedelta = timedelta(hours=2),
    ) -> None:
        if max_records < 2:
            raise ValueError("max_records must be at least 2")
        self._max_records = max_records
        self._ttl = ttl
        self._records: dict[UUID, deque[GoalContextRecord]] = {}
        self._lock = RLock()

    def append(self, session_id: UUID, record: GoalContextRecord) -> None:
        with self._lock:
            queue = self._records.setdefault(
                session_id,
                deque(maxlen=self._max_records),
            )
            queue.append(record)
            self._prune_locked(session_id, datetime.now(UTC))

    def recent(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[GoalContextRecord, ...]:
        checked_at = now or datetime.now(UTC)
        with self._lock:
            self._prune_locked(session_id, checked_at)
            return tuple(self._records.get(session_id, ()))

    def active_repository(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[str | None, str | None]:
        for record in reversed(self.recent(session_id, now=now)):
            if record.selected_repository:
                return record.selected_repository, record.selected_ref
        return None, None

    def clear(self, session_id: UUID) -> None:
        with self._lock:
            self._records.pop(session_id, None)

    def _prune_locked(self, session_id: UUID, now: datetime) -> None:
        queue = self._records.get(session_id)
        if queue is None:
            return
        cutoff = now - self._ttl
        while queue and queue[0].created_at < cutoff:
            queue.popleft()
        if not queue:
            self._records.pop(session_id, None)


_REFERENCE_TERMS = (
    " it",
    " its ",
    " that one",
    " this one",
    " the latest one",
    " the repository",
    " the repo",
)


def apply_repository_context(
    interpretation: GoalInterpretation,
    repository_full_name: str | None,
    ref: str | None,
) -> GoalInterpretation:
    """Use prior repository only when the current request lacks an explicit one."""

    if interpretation.entities.repository_full_name:
        return interpretation
    text = f" {interpretation.normalized_utterance} "
    if not repository_full_name or not any(term in text for term in _REFERENCE_TERMS):
        return interpretation

    owner, repository = repository_full_name.split("/", 1)
    entities = interpretation.entities.model_copy(
        update={
            "owner": owner,
            "repository": repository,
            "repository_full_name": repository_full_name,
            "ref": interpretation.entities.ref or ref,
        }
    )
    missing = tuple(
        field
        for field in interpretation.missing_fields
        if field != "repository"
    )
    updates: dict[str, object] = {
        "entities": entities,
        "missing_fields": missing,
        "confidence": max(interpretation.confidence, 0.88),
        "context_used": True,
        "rationale": (
            *interpretation.rationale,
            "Repository resolved from bounded session context.",
        ),
    }
    if interpretation.goal is GoalKind.AMBIGUOUS_REFERENCE:
        updates.update(
            {
                "domain": IntentDomain.GITHUB_WORKSPACE,
                "goal": GoalKind.GITHUB_REPOSITORY_INSPECT,
                "operation": OperationKind.READ,
                "confidence": 0.79,
                "rationale": (
                    *interpretation.rationale,
                    (
                        "A prior repository makes inspection plausible, "
                        "but confirmation is required."
                    ),
                ),
            }
        )
    return interpretation.model_copy(update=updates)

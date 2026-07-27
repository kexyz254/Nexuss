"""Short-lived conversation context, separate from durable memory."""

from __future__ import annotations

import re
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from nexuss.intelligence.models import (
    ContextResolution,
    ConversationTurn,
)

_REFERENCE_PATTERN = re.compile(
    r"\b(it|that|this|the topic|the answer|the second|the first|"
    r"second method|first method|third method)\b",
    re.IGNORECASE,
)
_ORDINALS = {"first": 0, "second": 1, "third": 2}


class ConversationContextStore:
    """Bounded process-local context with TTL and per-session isolation."""

    def __init__(
        self,
        *,
        max_turns: int = 20,
        ttl: timedelta = timedelta(hours=2),
    ) -> None:
        if max_turns < 2:
            raise ValueError("max_turns must be at least 2")
        self._max_turns = max_turns
        self._ttl = ttl
        self._turns: dict[UUID, deque[ConversationTurn]] = {}
        self._lock = RLock()

    def append(self, session_id: UUID, turn: ConversationTurn) -> None:
        with self._lock:
            queue = self._turns.setdefault(
                session_id,
                deque(maxlen=self._max_turns),
            )
            queue.append(turn)
            self._prune_locked(session_id, datetime.now(UTC))

    def recent(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[ConversationTurn, ...]:
        checked_at = now or datetime.now(UTC)
        with self._lock:
            self._prune_locked(session_id, checked_at)
            return tuple(self._turns.get(session_id, ()))

    def clear(self, session_id: UUID) -> None:
        with self._lock:
            self._turns.pop(session_id, None)

    def _prune_locked(self, session_id: UUID, now: datetime) -> None:
        queue = self._turns.get(session_id)
        if queue is None:
            return
        cutoff = now - self._ttl
        while queue and queue[0].created_at < cutoff:
            queue.popleft()
        if not queue:
            self._turns.pop(session_id, None)


class ContextResolver:
    """Resolve simple follow-ups without turning context into permission."""

    def resolve(
        self,
        query: str,
        turns: tuple[ConversationTurn, ...],
    ) -> ContextResolution:
        normalized = " ".join(query.split())
        prior = [turn for turn in turns if turn.role == "assistant"]
        last_assistant = prior[-1] if prior else None
        current_topic = self._current_topic(turns)

        if not _REFERENCE_PATTERN.search(normalized):
            return ContextResolution(
                original_query=normalized,
                resolved_query=normalized,
                current_topic=current_topic,
            )

        section = self._referenced_section(normalized, last_assistant)
        additions: list[str] = []
        if current_topic:
            additions.append(f"Current topic: {current_topic}.")
        if section:
            additions.append(f"Referenced section: {section}.")

        if not additions:
            return ContextResolution(
                original_query=normalized,
                resolved_query=normalized,
                current_topic=current_topic,
                confidence=0.45,
            )

        resolved = f"{normalized}\n\nContext: {' '.join(additions)}"
        return ContextResolution(
            original_query=normalized,
            resolved_query=resolved,
            current_topic=current_topic,
            referenced_section=section,
            used_prior_context=True,
            confidence=0.88 if section else 0.78,
        )

    @staticmethod
    def _current_topic(
        turns: tuple[ConversationTurn, ...],
    ) -> str | None:
        for turn in reversed(turns):
            if turn.topic:
                return turn.topic
        return None

    @staticmethod
    def _referenced_section(
        query: str,
        last_assistant: ConversationTurn | None,
    ) -> str | None:
        if last_assistant is None or not last_assistant.answer_sections:
            return None
        lowered = query.casefold()
        for word, index in _ORDINALS.items():
            if word in lowered and index < len(last_assistant.answer_sections):
                return last_assistant.answer_sections[index]
        return None

"""Deterministic evidence ranking with trust and freshness signals."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from nexuss.intelligence.models import EvidenceChunk, SourceKind

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "i", "in", "is", "it", "of", "on", "or", "that", "the",
    "this", "to", "was", "what", "when", "where", "which", "who",
    "why", "with", "you", "your",
}
_TRUST = {
    SourceKind.SYSTEM_VERIFIED: 1.0,
    SourceKind.CURATED_DOCUMENT: 0.95,
    SourceKind.PUBLIC_WEB: 0.78,
    SourceKind.USER_ASSERTED: 0.45,
}


def _terms(value: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _TOKEN.finditer(value)
        if match.group(0).casefold() not in _STOP
    }


class EvidenceRanker:
    def rank(
        self,
        query: str,
        chunks: tuple[EvidenceChunk, ...],
        *,
        limit: int,
        now: datetime | None = None,
    ) -> tuple[EvidenceChunk, ...]:
        query_terms = _terms(query)
        checked_at = now or datetime.now(UTC)
        ranked: list[EvidenceChunk] = []

        for chunk in chunks:
            chunk_terms = _terms(chunk.text + " " + chunk.source.title)
            overlap = (
                len(query_terms & chunk_terms) / max(1, len(query_terms))
            )
            trust = _TRUST[chunk.source.kind]
            freshness = self._freshness(chunk, checked_at)
            retrieval = chunk.retrieval_score

            score = min(
                1.0,
                0.50 * overlap
                + 0.25 * trust
                + 0.15 * retrieval
                + 0.10 * freshness,
            )
            ranked.append(chunk.model_copy(update={"rank_score": score}))

        ranked.sort(
            key=lambda item: (
                item.rank_score,
                item.retrieval_score,
                item.source.retrieved_at,
            ),
            reverse=True,
        )
        return tuple(ranked[:limit])

    @staticmethod
    def _freshness(
        chunk: EvidenceChunk,
        now: datetime,
    ) -> float:
        if chunk.source.published_at is None:
            return 0.65 if chunk.source.live else 0.45
        age_days = max(
            0.0,
            (now - chunk.source.published_at).total_seconds() / 86_400,
        )
        return max(0.0, math.exp(-age_days / 365.0))

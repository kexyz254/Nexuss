"""Fail-closed citation and claim verification."""

from __future__ import annotations

import re

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    DraftAnswer,
    EvidenceChunk,
    VerifiedClaim,
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "was", "were", "with",
}


def _terms(value: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _TOKEN.finditer(value)
        if match.group(0).casefold() not in _STOP
    }


class AnswerVerifier:
    def __init__(
        self,
        *,
        minimum_support: float = 0.08,
    ) -> None:
        self._minimum_support = minimum_support

    def verify(
        self,
        draft: DraftAnswer,
        evidence: tuple[EvidenceChunk, ...],
    ) -> tuple[VerifiedClaim, ...]:
        by_source: dict[str, list[EvidenceChunk]] = {}
        for chunk in evidence:
            by_source.setdefault(
                chunk.source.source_id,
                [],
            ).append(chunk)

        verified: list[VerifiedClaim] = []

        for claim in draft.claims:
            if not claim.citation_ids:
                raise IntelligenceError(
                    "INTELLIGENCE_CITATION_MISSING",
                    "A factual claim has no citation.",
                )

            missing = [
                citation_id
                for citation_id in claim.citation_ids
                if citation_id not in by_source
            ]
            if missing:
                raise IntelligenceError(
                    "INTELLIGENCE_CITATION_UNKNOWN",
                    "A claim cites evidence that was not supplied.",
                )

            claim_terms = _terms(claim.text)
            cited_terms: set[str] = set()
            for citation_id in claim.citation_ids:
                for chunk in by_source[citation_id]:
                    cited_terms |= _terms(chunk.text)

            support = (
                len(claim_terms & cited_terms)
                / max(1, len(claim_terms))
            )
            if support < self._minimum_support:
                raise IntelligenceError(
                    "INTELLIGENCE_CLAIM_UNSUPPORTED",
                    "A claim is not sufficiently supported by its citations.",
                )

            verified.append(
                VerifiedClaim(
                    text=claim.text,
                    citation_ids=claim.citation_ids,
                    confidence=claim.confidence,
                    support_score=min(1.0, support),
                )
            )

        if not verified:
            raise IntelligenceError(
                "INTELLIGENCE_NO_VERIFIED_CLAIMS",
                "The answer contained no verifiable claims.",
            )
        return tuple(verified)

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    DraftAnswer,
    DraftClaim,
    EvidenceChunk,
    EvidenceSource,
    SourceKind,
)
from nexuss.intelligence.verification import AnswerVerifier


def _evidence() -> tuple[EvidenceChunk, ...]:
    return (
        EvidenceChunk(
            chunk_id="c1",
            source=EvidenceSource(
                source_id="s1",
                title="Central bank policy",
                kind=SourceKind.PUBLIC_WEB,
                url="https://example.com/rates",
                retrieved_at=datetime.now(UTC),
                live=True,
            ),
            text=(
                "Higher interest rates can increase demand for a currency "
                "when other conditions remain comparable."
            ),
        ),
    )


def test_unknown_citation_fails_closed() -> None:
    draft = DraftAnswer(
        answer="Rates can affect currency demand.",
        claims=(
            DraftClaim(
                text="Higher rates can increase currency demand.",
                citation_ids=("missing",),
                confidence=0.8,
            ),
        ),
    )

    with pytest.raises(IntelligenceError) as raised:
        AnswerVerifier().verify(draft, _evidence())

    assert raised.value.code == "INTELLIGENCE_CITATION_UNKNOWN"


def test_supported_claim_is_verified() -> None:
    draft = DraftAnswer(
        answer="Rates can affect currency demand.",
        claims=(
            DraftClaim(
                text="Higher interest rates can increase currency demand.",
                citation_ids=("s1",),
                confidence=0.8,
            ),
        ),
    )

    claims = AnswerVerifier().verify(draft, _evidence())

    assert len(claims) == 1
    assert claims[0].support_score > 0.5

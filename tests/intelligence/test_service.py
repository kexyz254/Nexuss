from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.knowledge import StaticEvidenceRetriever
from nexuss.intelligence.models import (
    AnswerStyle,
    EvidenceChunk,
    EvidenceSource,
    IntelligenceRequest,
    SourceKind,
)
from nexuss.intelligence.provider import ExtractiveReasoningProvider
from nexuss.intelligence.router import ProviderRouter
from nexuss.intelligence.service import IntelligenceService


def _service(*, live: bool = True) -> IntelligenceService:
    source = EvidenceSource(
        source_id="forex-1",
        title="Foreign exchange market overview",
        kind=SourceKind.PUBLIC_WEB,
        url="https://example.com/forex",
        retrieved_at=datetime.now(UTC),
        live=live,
    )
    chunks = (
        EvidenceChunk(
            chunk_id="forex-1-a",
            source=source,
            text=(
                "The foreign exchange market is a global market where "
                "participants exchange one currency for another. Exchange "
                "rates respond to interest rates, inflation expectations, "
                "economic growth, political risk, and market sentiment."
            ),
            retrieval_score=0.95,
        ),
        EvidenceChunk(
            chunk_id="forex-1-b",
            source=source,
            text=(
                "Risk management commonly includes position sizing, "
                "stop-loss orders, and limits on total portfolio exposure."
            ),
            retrieval_score=0.82,
        ),
    )
    return IntelligenceService(
        retriever=StaticEvidenceRetriever("test", chunks),
        provider_router=ProviderRouter(
            local_provider=ExtractiveReasoningProvider(),
        ),
    )


def test_end_to_end_answer_is_grounded_and_verified() -> None:
    request = IntelligenceRequest(
        session_id=uuid4(),
        query="Explain the foreign exchange market.",
        style=AnswerStyle.BEGINNER,
    )

    answer = _service().answer(request)

    assert answer.verified is True
    assert answer.grounded is True
    assert answer.sources
    assert answer.claims
    assert answer.provider_id == "local_extractive_v1"
    assert "[forex-1]" in answer.answer


def test_current_question_requires_live_evidence() -> None:
    request = IntelligenceRequest(
        session_id=uuid4(),
        query="What is the latest forex market state?",
        requires_live_sources=True,
    )

    with pytest.raises(IntelligenceError) as raised:
        _service(live=False).answer(request)

    assert raised.value.code == (
        "INTELLIGENCE_FRESH_EVIDENCE_REQUIRED"
    )

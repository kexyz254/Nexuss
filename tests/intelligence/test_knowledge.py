from __future__ import annotations

from datetime import UTC, datetime

from nexuss.intelligence.knowledge import (
    CompositeRetriever,
    StaticEvidenceRetriever,
)
from nexuss.intelligence.models import (
    EvidenceChunk,
    EvidenceSource,
    SourceKind,
)


def _chunk(chunk_id: str, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        source=EvidenceSource(
            source_id="source-1",
            title="Forex overview",
            kind=SourceKind.PUBLIC_WEB,
            url="https://example.com/forex",
            retrieved_at=datetime.now(UTC),
            live=True,
        ),
        text=text,
        retrieval_score=0.8,
    )


def test_composite_retriever_deduplicates_equivalent_chunks() -> None:
    chunk = _chunk(
        "c1",
        "Foreign exchange trading compares the value of currencies.",
    )
    retriever = CompositeRetriever(
        (
            StaticEvidenceRetriever("a", (chunk,)),
            StaticEvidenceRetriever(
                "b",
                (chunk.model_copy(update={"chunk_id": "c2"}),),
            ),
        )
    )

    result = retriever.retrieve("foreign exchange", limit=5)

    assert len(result) == 1

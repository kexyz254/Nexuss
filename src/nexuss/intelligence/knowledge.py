"""Read-only evidence retrieval adapters and composition."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    EvidenceChunk,
    EvidenceSource,
    SourceKind,
)


class EvidenceRetriever(Protocol):
    retriever_id: str

    def retrieve(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[EvidenceChunk, ...]: ...


class StaticEvidenceRetriever:
    """Deterministic retriever for tests, curated knowledge, and documents."""

    def __init__(
        self,
        retriever_id: str,
        chunks: Iterable[EvidenceChunk],
    ) -> None:
        self.retriever_id = retriever_id
        self._chunks = tuple(chunks)

    def retrieve(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        terms = {
            token.casefold()
            for token in query.split()
            if len(token) > 2
        }

        def score(chunk: EvidenceChunk) -> tuple[int, float]:
            text_terms = set(chunk.text.casefold().split())
            return (
                len(terms & text_terms),
                chunk.retrieval_score,
            )

        return tuple(
            sorted(self._chunks, key=score, reverse=True)[:limit]
        )


class ExistingKnowledgeProviderAdapter:
    """Adapt the existing P5 provider result shape: sources + brief."""

    retriever_id = "existing_knowledge_provider"

    def __init__(self, provider: object) -> None:
        self._provider = provider

    def retrieve(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        research = getattr(self._provider, "research", None)
        if not callable(research):
            raise IntelligenceError(
                "INTELLIGENCE_RETRIEVER_INVALID",
                "The configured knowledge provider has no research method.",
            )

        result = research(query)
        if not isinstance(result, dict):
            raise IntelligenceError(
                "INTELLIGENCE_RETRIEVER_INVALID",
                "The knowledge provider returned an invalid result.",
            )

        raw_sources = result.get("sources", [])
        if not isinstance(raw_sources, list):
            raise IntelligenceError(
                "INTELLIGENCE_RETRIEVER_INVALID",
                "The knowledge provider sources are invalid.",
            )

        chunks: list[EvidenceChunk] = []
        for index, raw in enumerate(raw_sources[:limit], start=1):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            url = str(raw.get("url", "")).strip() or None
            extract = str(raw.get("extract", "")).strip()
            if not title or not extract:
                continue
            source_id = f"web-{index}"
            source = EvidenceSource(
                source_id=source_id,
                title=title,
                kind=SourceKind.PUBLIC_WEB,
                url=url,
                publisher=str(raw.get("provider", "")).strip() or None,
                live=True,
            )
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{source_id}-chunk-1",
                    source=source,
                    text=extract,
                    retrieval_score=0.7,
                )
            )
        return tuple(chunks)


class CompositeRetriever:
    """Collect, bound, and deduplicate evidence from multiple retrievers."""

    def __init__(
        self,
        retrievers: Iterable[EvidenceRetriever],
    ) -> None:
        self._retrievers = tuple(retrievers)
        if not self._retrievers:
            raise ValueError("at least one retriever is required")

    def retrieve(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[EvidenceChunk, ...]:
        collected: list[EvidenceChunk] = []
        failures: list[str] = []

        for retriever in self._retrievers:
            try:
                collected.extend(
                    retriever.retrieve(query, limit=limit)
                )
            except Exception as exc:  # noqa: BLE001 - isolate third-party retrievers
                failures.append(
                    f"{getattr(retriever, 'retriever_id', 'unknown')}:"
                    f"{type(exc).__name__}"
                )

        if not collected and failures:
            raise IntelligenceError(
                "INTELLIGENCE_ALL_RETRIEVERS_FAILED",
                "All configured evidence retrievers failed.",
                retryable=True,
            )

        deduplicated: list[EvidenceChunk] = []
        seen: set[tuple[str, str]] = set()
        for chunk in collected:
            key = (
                str(chunk.source.url or chunk.source.title).casefold(),
                " ".join(chunk.text.casefold().split())[:300],
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(chunk)

        return tuple(deduplicated[: limit * 2])

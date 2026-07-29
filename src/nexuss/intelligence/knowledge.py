"""Read-only evidence retrieval adapters and composition."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    EvidenceChunk,
    EvidenceSource,
    SourceKind,
)
from nexuss.knowledge.provider import KnowledgeProviderError


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



_RETRIEVAL_PREFIX = re.compile(
    r"^(?:please\s+)?(?:"
    r"explain|define|describe|tell me about|"
    r"what do you know about|"
    r"what is|what are|who is|who was"
    r")\s+",
    re.IGNORECASE,
)

_RETRIEVAL_SUFFIX = re.compile(
    r"\s+(?:"
    r"in simple terms|simply|for a beginner|"
    r"briefly|in detail"
    r")[.!?]*$",
    re.IGNORECASE,
)

_RETRIEVAL_FOLLOWUP_CLAUSE = re.compile(
    r"\s+(?:and|,)\s+"
    r"(?:why|how|what|when|where|who|which)\b.*$",
    re.IGNORECASE,
)


_RETRIEVAL_TOKEN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9'\-]*"
)


def _normalize_retrieval_query(query: str) -> str:
    normalized = " ".join(query.split()).strip(" .!?")
    normalized = _RETRIEVAL_PREFIX.sub("", normalized)
    normalized = _RETRIEVAL_FOLLOWUP_CLAUSE.sub(
        "",
        normalized,
    )
    normalized = _RETRIEVAL_SUFFIX.sub("", normalized)
    return normalized.strip(" .!?") or query.strip()


def _retrieval_terms(value: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _RETRIEVAL_TOKEN.finditer(value)
        if len(match.group(0)) > 2
    }


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

        retrieval_query = _normalize_retrieval_query(
            query
        )
        try:
            result = research(retrieval_query)
        except KnowledgeProviderError as exc:
            code = str(exc)

            if code == "KNOWLEDGE_NO_SOURCES":
                raise IntelligenceError(
                    "INTELLIGENCE_NO_EVIDENCE",
                    (
                        "The public knowledge provider returned "
                        "no relevant evidence."
                    ),
                ) from exc

            if code == "KNOWLEDGE_PROVIDER_FORBIDDEN":
                raise IntelligenceError(
                    "INTELLIGENCE_RETRIEVER_FORBIDDEN",
                    (
                        "The public knowledge provider refused "
                        "the request."
                    ),
                ) from exc

            raise IntelligenceError(
                "INTELLIGENCE_RETRIEVER_UNAVAILABLE",
                (
                    "The public knowledge provider could not "
                    "return usable evidence."
                ),
                retryable=True,
            ) from exc

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

        normalized_topic = " ".join(
            retrieval_query.casefold().split()
        ).strip(" .!?")

        exact_title_available = any(
            (
                isinstance(raw, dict)
                and " ".join(
                    str(
                        raw.get("title", "")
                    ).casefold().split()
                ).strip(" .!?")
                == normalized_topic
            )
            for raw in raw_sources
        )

        query_terms = _retrieval_terms(
            retrieval_query
        )

        chunks: list[EvidenceChunk] = []
        for index, raw in enumerate(
            raw_sources[:limit],
            start=1,
        ):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            url = str(raw.get("url", "")).strip() or None
            extract = str(raw.get("extract", "")).strip()
            if not title or not extract:
                continue

            normalized_title = " ".join(
                title.casefold().split()
            ).strip(" .!?")

            if (
                exact_title_available
                and normalized_title != normalized_topic
            ):
                continue

            title_terms = _retrieval_terms(title)
            extract_terms = _retrieval_terms(extract)

            title_overlap = (
                len(query_terms & title_terms)
                / max(1, len(query_terms))
            )
            body_overlap = (
                len(query_terms & extract_terms)
                / max(1, len(query_terms))
            )

            if (
                query_terms
                and title_overlap == 0.0
                and body_overlap == 0.0
            ):
                continue

            retrieval_score = min(
                1.0,
                0.55
                + 0.35 * title_overlap
                + 0.10 * body_overlap,
            )

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
                    retrieval_score=retrieval_score,
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

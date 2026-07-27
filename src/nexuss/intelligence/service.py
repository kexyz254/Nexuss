"""End-to-end orchestration for grounded conversational intelligence."""

from __future__ import annotations

from nexuss.intelligence.context import (
    ContextResolver,
    ConversationContextStore,
)
from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.knowledge import EvidenceRetriever
from nexuss.intelligence.models import (
    ConversationTurn,
    IntelligenceAnswer,
    IntelligenceRequest,
)
from nexuss.intelligence.ranking import EvidenceRanker
from nexuss.intelligence.router import ProviderRouter
from nexuss.intelligence.verification import AnswerVerifier


class IntelligenceService:
    """Read-only intelligence pipeline; it cannot execute external actions."""

    def __init__(
        self,
        *,
        retriever: EvidenceRetriever,
        provider_router: ProviderRouter,
        context_store: ConversationContextStore | None = None,
        context_resolver: ContextResolver | None = None,
        ranker: EvidenceRanker | None = None,
        verifier: AnswerVerifier | None = None,
    ) -> None:
        self._retriever = retriever
        self._providers = provider_router
        self._context = context_store or ConversationContextStore()
        self._resolver = context_resolver or ContextResolver()
        self._ranker = ranker or EvidenceRanker()
        self._verifier = verifier or AnswerVerifier()

    def answer(
        self,
        request: IntelligenceRequest,
    ) -> IntelligenceAnswer:
        turns = self._context.recent(request.session_id)
        resolution = self._resolver.resolve(request.query, turns)

        raw = self._retriever.retrieve(
            resolution.resolved_query,
            limit=request.max_sources,
        )
        ranked = self._ranker.rank(
            resolution.resolved_query,
            raw,
            limit=request.max_sources,
        )
        bounded = self._bound_evidence(
            ranked,
            request.max_evidence_chars,
        )

        if request.requires_live_sources and not any(
            chunk.source.live for chunk in bounded
        ):
            raise IntelligenceError(
                "INTELLIGENCE_FRESH_EVIDENCE_REQUIRED",
                "This question requires current evidence, but no live source was available.",
            )

        if not bounded:
            raise IntelligenceError(
                "INTELLIGENCE_NO_EVIDENCE",
                "No relevant evidence was available for a grounded answer.",
            )

        provider = self._providers.select(request)
        draft = provider.generate(
            query=resolution.resolved_query,
            style=request.style,
            context=resolution,
            evidence=bounded,
        )
        verified_claims = self._verifier.verify(draft, bounded)

        unique_sources = []
        seen_sources: set[str] = set()
        cited = {
            citation_id
            for claim in verified_claims
            for citation_id in claim.citation_ids
        }
        for chunk in bounded:
            if (
                chunk.source.source_id in cited
                and chunk.source.source_id not in seen_sources
            ):
                seen_sources.add(chunk.source.source_id)
                unique_sources.append(chunk.source)

        answer = IntelligenceAnswer(
            request_id=request.request_id,
            session_id=request.session_id,
            answer=draft.answer,
            claims=verified_claims,
            sources=tuple(unique_sources),
            limitations=draft.limitations,
            provider_id=provider.provider_id,
            provider_kind=provider.kind,
            intelligence_mode=request.mode,
            context=resolution,
            grounded=True,
            verified=True,
        )

        self._context.append(
            request.session_id,
            ConversationTurn(
                role="user",
                content=request.query,
                topic=resolution.current_topic or request.query,
            ),
        )
        self._context.append(
            request.session_id,
            ConversationTurn(
                role="assistant",
                content=answer.answer,
                topic=resolution.current_topic or request.query,
                answer_sections=draft.suggested_sections,
            ),
        )
        return answer

    @staticmethod
    def _bound_evidence(
        chunks: tuple,
        maximum_chars: int,
    ) -> tuple:
        selected = []
        used = 0
        for chunk in chunks:
            remaining = maximum_chars - used
            if remaining <= 0:
                break
            if len(chunk.text) <= remaining:
                selected.append(chunk)
                used += len(chunk.text)
                continue
            if remaining >= 300:
                selected.append(
                    chunk.model_copy(
                        update={"text": chunk.text[:remaining]}
                    )
                )
            break
        return tuple(selected)

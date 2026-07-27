from __future__ import annotations

import json

import httpx

from nexuss.intelligence.models import (
    AnswerStyle,
    ContextResolution,
    EvidenceChunk,
    EvidenceSource,
    SourceKind,
)
from nexuss.intelligence.provider import (
    OpenAICompatibleReasoningProvider,
)


def test_remote_provider_sends_bearer_and_parses_json(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEXUSS_REASONING_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        content = {
            "answer": "Currencies are exchanged globally. [s1]",
            "claims": [
                {
                    "text": "Currencies are exchanged globally.",
                    "citation_ids": ["s1"],
                    "confidence": 0.8,
                }
            ],
            "limitations": [],
            "suggested_sections": ["Overview"],
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(content),
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleReasoningProvider(
        base_url="https://reasoning.example.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    evidence = (
        EvidenceChunk(
            chunk_id="c1",
            source=EvidenceSource(
                source_id="s1",
                title="Overview",
                kind=SourceKind.PUBLIC_WEB,
                url="https://example.com",
                live=True,
            ),
            text="Currencies are exchanged globally.",
        ),
    )

    result = provider.generate(
        query="Explain currencies.",
        style=AnswerStyle.DIRECT,
        context=ContextResolution(
            original_query="Explain currencies.",
            resolved_query="Explain currencies.",
        ),
        evidence=evidence,
    )

    assert result.claims[0].citation_ids == ("s1",)

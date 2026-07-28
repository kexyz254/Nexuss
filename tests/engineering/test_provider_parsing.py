from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from nexuss.engineering.models import ProviderKind
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.engineering.providers.openai_compatible import OpenAICompatibleProvider


def test_openai_compatible_provider_parses_structured_proposal() -> None:
    proposal = {
        "summary": "Create the landing page files.",
        "tool_requests": [],
        "done": True,
        "completion_message": "Done.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer hidden"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(proposal)}}]},
        )

    profile = ProviderProfile(
        provider_id="deepseek-main",
        kind=ProviderKind.DEEPSEEK,
        model="deepseek-chat",
        api_base="https://api.deepseek.com",
    )
    provider = OpenAICompatibleProvider(
        profile,
        SecretStr("hidden"),
        transport=httpx.MockTransport(handler),
    )
    result = provider.propose(
        ProviderRequest(system_prompt="system", user_prompt="user")
    )
    assert result.done
    assert result.completion_message == "Done."

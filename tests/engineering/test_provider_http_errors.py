from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ProviderKind
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.providers.base import (
    ProviderRequest,
)
from nexuss.engineering.providers.openai_compatible import (
    OpenAICompatibleProvider,
)


def _provider(
    status_code: int,
) -> OpenAICompatibleProvider:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            status_code,
            json={"error": {"message": "not exposed"}},
        )

    return OpenAICompatibleProvider(
        ProviderProfile(
            provider_id="deepseek",
            kind=ProviderKind.DEEPSEEK,
            model="deepseek-v4-pro",
            api_base="https://api.deepseek.com",
        ),
        SecretStr("hidden-key"),
        transport=httpx.MockTransport(handler),
    )


def test_402_maps_to_insufficient_balance() -> None:
    provider = _provider(402)

    with pytest.raises(EngineeringError) as captured:
        provider.propose(
            ProviderRequest(
                system_prompt="system",
                user_prompt="user",
            )
        )

    assert captured.value.code == (
        "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
    )
    assert captured.value.retryable is False
    assert "hidden-key" not in str(captured.value)


def test_429_maps_to_retryable_rate_limit() -> None:
    provider = _provider(429)

    with pytest.raises(EngineeringError) as captured:
        provider.propose(
            ProviderRequest(
                system_prompt="system",
                user_prompt="user",
            )
        )

    assert captured.value.code == (
        "ENGINEERING_PROVIDER_RATE_LIMITED"
    )
    assert captured.value.retryable is True

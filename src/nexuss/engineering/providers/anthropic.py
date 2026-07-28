"""Anthropic Messages API adapter."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ModelProposal
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.engineering.providers.common import parse_proposal_text


class AnthropicProvider:
    def __init__(
        self,
        profile: ProviderProfile,
        api_key: SecretStr,
        *,
        timeout_seconds: float = 90.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profile = profile
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def propose(self, request: ProviderRequest) -> ModelProposal:
        body = {
            "model": self.profile.model,
            "max_tokens": self.profile.max_output_tokens,
            "temperature": 0,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
        }
        try:
            with httpx.Client(
                base_url=self.profile.api_base.rstrip("/"),
                timeout=self._timeout_seconds,
                transport=self._transport,
                headers={
                    "x-api-key": self._api_key.get_secret_value(),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "User-Agent": "Nexuss-Engineering/1.0",
                },
            ) as client:
                response = client.post("/v1/messages", json=body)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_UNAVAILABLE",
                "The selected engineering provider is unavailable.",
                retryable=True,
            ) from exc

        try:
            blocks = payload["content"]
            text = "\n".join(
                str(block.get("text", ""))
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider response did not contain a proposal.",
            ) from exc
        return parse_proposal_text(text)

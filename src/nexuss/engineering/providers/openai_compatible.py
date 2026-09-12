"""OpenAI-compatible adapter used for OpenAI and DeepSeek profiles."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ModelProposal
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.engineering.providers.common import parse_proposal_text


class OpenAICompatibleProvider:
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
            "messages": [
                {
                    "role": "system",
                    "content": request.system_prompt,
                },
                {
                    "role": "user",
                    "content": request.user_prompt,
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": self.profile.max_output_tokens,
        }

        if self.profile.provider_id == "deepseek":
            body["thinking"] = {"type": "disabled"}
            body["tool_choice"] = "none"

        try:
            with httpx.Client(
                base_url=self.profile.api_base.rstrip("/"),
                timeout=self._timeout_seconds,
                transport=self._transport,
                headers={
                    "Authorization": (
                        "Bearer "
                        f"{self._api_key.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                    "User-Agent": "Nexuss-Engineering/1.2",
                },
            ) as client:
                response = client.post(
                    "/chat/completions",
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 402:
                code = (
                    "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
                )
                message = (
                    "The selected engineering provider has "
                    "insufficient API balance."
                )
                retryable = False
            elif status_code in {401, 403}:
                code = (
                    "ENGINEERING_PROVIDER_CREDENTIAL_REJECTED"
                )
                message = (
                    "The selected engineering provider rejected "
                    "its encrypted credential."
                )
                retryable = False
            elif status_code == 422:
                code = "ENGINEERING_PROVIDER_REQUEST_INVALID"
                message = (
                    "The selected engineering provider rejected "
                    "the model request contract."
                )
                retryable = False
            elif status_code == 429:
                code = "ENGINEERING_PROVIDER_RATE_LIMITED"
                message = (
                    "The selected engineering provider "
                    "rate-limited the request."
                )
                retryable = True
            else:
                code = "ENGINEERING_PROVIDER_UNAVAILABLE"
                message = (
                    "The selected engineering provider "
                    "is unavailable."
                )
                retryable = status_code >= 500

            raise EngineeringError(
                code,
                message,
                retryable=retryable,
                safe_details={"status_code": status_code},
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_UNAVAILABLE",
                "The selected engineering provider is unavailable.",
                retryable=True,
            ) from exc

        try:
            content = payload["choices"][0]["message"][
                "content"
            ]
        except (KeyError, IndexError, TypeError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider response did not contain a proposal.",
            ) from exc
        return parse_proposal_text(str(content))

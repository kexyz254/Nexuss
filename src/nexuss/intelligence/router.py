"""Privacy-preserving provider selection."""

from __future__ import annotations

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    ContentSensitivity,
    IntelligenceMode,
    IntelligenceRequest,
    ProviderKind,
)
from nexuss.intelligence.provider import ReasoningProvider


class ProviderRouter:
    def __init__(
        self,
        *,
        local_provider: ReasoningProvider,
        external_provider: ReasoningProvider | None = None,
    ) -> None:
        if local_provider.kind is not ProviderKind.LOCAL:
            raise ValueError("local_provider must declare kind=local")
        self._local = local_provider
        self._external = external_provider

    def select(self, request: IntelligenceRequest) -> ReasoningProvider:
        if request.mode is IntelligenceMode.LOCAL_ONLY:
            return self._require_available(self._local)

        if request.sensitivity is not ContentSensitivity.PUBLIC:
            return self._require_available(self._local)

        if not request.external_processing_approved:
            raise IntelligenceError(
                "INTELLIGENCE_EXTERNAL_APPROVAL_REQUIRED",
                "External reasoning requires explicit approval for this request.",
            )

        if self._external is None:
            raise IntelligenceError(
                "INTELLIGENCE_PROVIDER_NOT_CONFIGURED",
                "No external reasoning provider is configured.",
            )

        return self._require_available(self._external)

    @staticmethod
    def _require_available(
        provider: ReasoningProvider,
    ) -> ReasoningProvider:
        health = provider.health()
        if not health.available:
            raise IntelligenceError(
                "INTELLIGENCE_PROVIDER_UNAVAILABLE",
                health.detail,
                retryable=True,
            )
        return provider

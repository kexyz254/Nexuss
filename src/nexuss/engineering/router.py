"""Explicit engineering-provider routing."""

from __future__ import annotations

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import EngineeringTaskSpec, ModelProposal
from nexuss.engineering.policy import EngineeringPolicy, ProviderProfile
from nexuss.engineering.providers.base import EngineeringProvider, ProviderRequest


class EngineeringProviderRouter:
    def __init__(self, providers: tuple[EngineeringProvider, ...]) -> None:
        self._providers = {
            provider.profile.provider_id: provider
            for provider in providers
        }

    def profile(self, provider_id: str) -> ProviderProfile:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_UNKNOWN",
                "The requested engineering provider is not registered.",
            )
        return provider.profile

    def propose(
        self,
        task: EngineeringTaskSpec,
        request: ProviderRequest,
    ) -> ModelProposal:
        provider = self._providers.get(task.provider_id)
        if provider is None:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_UNKNOWN",
                "The requested engineering provider is not registered.",
            )
        EngineeringPolicy.authorize_provider(task, provider.profile)
        return provider.propose(request)

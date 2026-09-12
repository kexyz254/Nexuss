"""Resolve configured AI providers behind one Nexuss interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from nexuss.ai.models import AIProviderProfile
from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.models import (
    EngineeringTaskSpec,
    ModelProposal,
    TaskSensitivity,
    WorkspaceKind,
)
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)
from nexuss.engineering.providers.base import ProviderRequest


class AIProviderConnectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedAIProvider:
    profile: AIProviderProfile
    model: str
    proposer: Callable[[ProviderRequest], ModelProposal]


class AIProviderConnectionResolver:
    """Provider-specific connection code isolated behind one resolver."""

    def __init__(self, *, timeout_seconds: float = 120.0) -> None:
        self._connections = EngineeringProviderConnectionService(
            DpapiSecretVault(),
            timeout_seconds=timeout_seconds,
        )

    def resolve(
        self,
        *,
        profile: AIProviderProfile,
        request_id: UUID,
        instruction: str,
        external_processing_approved: bool,
    ) -> ResolvedAIProvider:
        if not profile.local_processing and not external_processing_approved:
            raise AIProviderConnectionError(
                "AI_EXTERNAL_PROCESSING_NOT_APPROVED",
                "External AI processing requires explicit approval.",
            )

        if profile.provider_id != "deepseek":
            raise AIProviderConnectionError(
                "AI_PROVIDER_ADAPTER_NOT_CONFIGURED",
                (
                    f"{profile.display_name} is registered, but its "
                    "connection adapter is not configured."
                ),
            )

        access = self._connections.deepseek_access()
        if not access.available:
            raise AIProviderConnectionError(
                access.code.value,
                access.user_message,
            )

        router = self._connections.build_deepseek_router()
        engineering_profile = router.profile("deepseek")

        task = EngineeringTaskSpec(
            task_id=request_id,
            goal=instruction,
            provider_id="deepseek",
            workspace_kind=WorkspaceKind.LOCAL,
            sensitivity=TaskSensitivity.PRIVATE,
            external_processing_approved=external_processing_approved,
            allowed_tools=(),
            max_rounds=1,
            max_files_changed=1,
            max_runtime_seconds=120,
        )

        return ResolvedAIProvider(
            profile=profile,
            model=engineering_profile.model,
            proposer=lambda request: router.propose(task, request),
        )

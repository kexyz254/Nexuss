"""Provider and workspace policy for engineering tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import (
    EngineeringTaskSpec,
    ProviderKind,
    TaskSensitivity,
)


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=80)
    kind: ProviderKind
    model: str = Field(min_length=1, max_length=160)
    api_base: str = Field(min_length=1, max_length=500)
    external: bool = True
    enabled: bool = True
    max_output_tokens: int = Field(default=8_000, ge=256, le=64_000)


class EngineeringPolicy:
    """Fail-closed policy for model processing and engineering workspaces."""

    @staticmethod
    def authorize_provider(
        task: EngineeringTaskSpec,
        profile: ProviderProfile,
    ) -> None:
        if not profile.enabled:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_DISABLED",
                "The requested engineering provider is disabled.",
            )

        if not profile.external:
            return

        if task.sensitivity is TaskSensitivity.RESTRICTED:
            raise EngineeringError(
                "ENGINEERING_EXTERNAL_RESTRICTED",
                "Restricted task data cannot be sent to an external provider.",
            )

        if (
            task.sensitivity is TaskSensitivity.PRIVATE
            and not task.external_processing_approved
        ):
            raise EngineeringError(
                "ENGINEERING_EXTERNAL_APPROVAL_REQUIRED",
                "Private repository content requires per-task external-processing approval.",
            )

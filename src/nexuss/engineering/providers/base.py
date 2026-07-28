"""Provider protocol."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.models import ModelProposal
from nexuss.engineering.policy import ProviderProfile


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system_prompt: str = Field(min_length=1, max_length=50_000)
    user_prompt: str = Field(min_length=1, max_length=200_000)


class EngineeringProvider(Protocol):
    profile: ProviderProfile

    def propose(self, request: ProviderRequest) -> ModelProposal: ...

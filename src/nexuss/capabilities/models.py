"""Sanitized provider-visible capability models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nexuss.ai.models import RequestedAction


class CapabilityMappingState(StrEnum):
    VERIFIED_EXISTING = "verified_existing"
    SIMULATED = "simulated"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class CapabilityCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    title: str
    risk_tier: str
    approval_policy: str
    approval_channel: str | None
    execution_mode: str
    status: str
    reversible: bool
    provider_can_request: bool
    provider_can_execute: Literal[False] = False


class MappedRequestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: RequestedAction
    mapping_state: CapabilityMappingState
    reason_code: str
    explanation: str
    risk_tier: str | None = None
    approval_policy: str | None = None
    approval_channel: str | None = None
    execution_mode: str | None = None
    capability_status: str | None = None
    reversible: bool | None = None
    execution_authorized: Literal[False] = False

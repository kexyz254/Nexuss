"""Common contracts shared by all Nexuss external-system connectors."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ConnectorStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    REAUTH_REQUIRED = "reauth_required"


class ConnectorIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: str
    external_account_id: str
    account_label: str
    account_type: str
    verified: bool
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConnectorHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: str
    status: ConnectorStatus
    configured: bool
    identity: ConnectorIdentity | None = None
    detail: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Connector(Protocol):
    connector_id: str

    def health(self) -> ConnectorHealth: ...

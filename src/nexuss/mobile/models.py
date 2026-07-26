"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Typed contracts for the confidential P4 phone-approval client.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.domain.models import ApprovalDecisionKind, RiskTier


class MobilePairingChallenge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairing_id: UUID
    pairing_code: str = Field(pattern=r"^[0-9]{8}$")
    mobile_url: str
    expires_at: datetime


class MobilePairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pairing_code: str = Field(pattern=r"^[0-9]{8}$")
    device_label: str = Field(min_length=1, max_length=80)


class MobileDeviceSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: UUID
    device_label: str
    device_token: str = Field(min_length=40, max_length=256)
    expires_at: datetime


class MobileApprovalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    approval_id: UUID
    approval_token: str = Field(min_length=32, max_length=256)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_title: str
    action_summary: str
    exact_preview: str
    destination_label: str
    risk_tier: RiskTier
    reversible: bool
    expires_at: datetime


class MobileDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    approval_token: str = Field(min_length=32, max_length=256)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ApprovalDecisionKind

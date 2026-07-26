"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Signed contracts exchanged between Nexuss Core and trusted device nodes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeviceCommandEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    task_id: UUID
    capability_id: str = Field(pattern=r"^device\.[a-z0-9_.-]+$")
    target_node_id: str = Field(min_length=1, max_length=120)
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=32, max_length=128)
    parameters: dict[str, object] = Field(default_factory=dict)


class DeviceCommandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    node_id: str
    node_hostname: str
    capability_id: str
    executable: str
    process_id: int = Field(gt=0)
    started_at: datetime
    verified_running: bool
    source_mode: str = "live_trusted_device_node"


class DeviceRollbackEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rollback_id: UUID
    task_id: UUID
    command_id: UUID
    target_node_id: str = Field(min_length=1, max_length=120)
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=32, max_length=128)


class DeviceRollbackEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rollback_id: UUID
    command_id: UUID
    node_id: str
    process_id: int = Field(gt=0)
    terminated: bool
    verified_absent: bool
    observed_at: datetime
    source_mode: str = "live_trusted_device_node_rollback"

"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Channel(StrEnum):
    VOICE = "voice"
    TEXT = "text"


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    channel: Channel
    utterance: str = Field(min_length=1, max_length=10_000)
    user_session_id: UUID
    target_devices: list[str] = Field(default_factory=list)
    requested_at: datetime
    client_context: dict[str, object] = Field(default_factory=dict)

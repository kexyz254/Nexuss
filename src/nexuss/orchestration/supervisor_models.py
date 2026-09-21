"""Agent Supervisor contracts for the Nexuss orchestration control plane."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentKind(StrEnum):
    CORE = "core"
    ENGINEERING = "engineering"
    RESEARCH = "research"
    DEVICE = "device"
    OPERATIONS = "operations"
    COLLABORATION = "collaboration"
    EXTERNAL = "external"


class AgentStatus(StrEnum):
    HEALTHY = "healthy"
    BUSY = "busy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SupervisorAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=160)
    kind: AgentKind
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.UNKNOWN
    heartbeat_at: datetime
    stale_after_seconds: int = Field(default=30, ge=5, le=86_400)
    current_task_id: UUID | None = None
    current_task_state: str | None = Field(default=None, max_length=80)
    registered_at: datetime
    updated_at: datetime
    metadata: dict[str, str] = Field(default_factory=dict)


class SupervisorTaskProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    state: str = Field(min_length=1, max_length=80)
    capability_ids: tuple[str, ...]
    assigned_agents: tuple[str, ...]
    approval_required: bool = False
    created_at: datetime
    updated_at: datetime


class SupervisorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=120)
    severity: EventSeverity
    source_agent_id: str = Field(min_length=1, max_length=120)
    task_id: UUID | None = None
    detail: str = Field(min_length=1, max_length=2_000)
    occurred_at: datetime
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SupervisorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agents: tuple[SupervisorAgent, ...]
    active_tasks: tuple[SupervisorTaskProjection, ...]
    recent_events: tuple[SupervisorEvent, ...]
    healthy_count: int = Field(ge=0)
    busy_count: int = Field(ge=0)
    degraded_count: int = Field(ge=0)
    offline_count: int = Field(ge=0)
    event_chain_valid: bool
    authority: str = "core_task_state_machine"
    external_execution_authorized: bool = False
    observed_at: datetime


class RegisterSupervisorAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    title: str = Field(min_length=1, max_length=160)
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    stale_after_seconds: int = Field(default=30, ge=5, le=86_400)
    metadata: dict[str, str] = Field(default_factory=dict)


class SupervisorHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus = AgentStatus.HEALTHY
    current_task_id: UUID | None = None
    current_task_state: str | None = Field(default=None, max_length=80)
    detail: str = Field(default="", max_length=2_000)

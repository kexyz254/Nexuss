"""Validated engineering-plane data contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    LOCAL = "local"


class WorkspaceKind(StrEnum):
    LOCAL = "local"
    CODESPACE = "codespace"


class TaskSensitivity(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class ToolName(StrEnum):
    READ_FILE = "workspace.read_file"
    WRITE_FILE = "workspace.write_file"
    LIST_FILES = "workspace.list_files"
    RUN_COMMAND = "workspace.run_command"


class EngineeringTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID = Field(default_factory=uuid4)
    goal: str = Field(min_length=1, max_length=20_000)
    provider_id: str = Field(min_length=1, max_length=80)
    workspace_kind: WorkspaceKind = WorkspaceKind.LOCAL
    sensitivity: TaskSensitivity = TaskSensitivity.PRIVATE
    external_processing_approved: bool = False
    allowed_tools: tuple[ToolName, ...] = (
        ToolName.READ_FILE,
        ToolName.WRITE_FILE,
        ToolName.LIST_FILES,
        ToolName.RUN_COMMAND,
    )
    max_rounds: int = Field(default=8, ge=1, le=30)
    max_files_changed: int = Field(default=20, ge=1, le=200)
    max_runtime_seconds: int = Field(default=300, ge=5, le=3600)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    tool_name: ToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=2_000)


class ModelProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=8_000)
    tool_requests: tuple[ToolRequest, ...] = ()
    done: bool = False
    completion_message: str | None = Field(default=None, max_length=8_000)

    @field_validator("completion_message")
    @classmethod
    def completion_required_when_done(cls, value: str | None, info):
        if info.data.get("done") and not value:
            raise ValueError("completion_message is required when done")
        return value


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    tool_name: ToolName
    success: bool
    output: str = Field(max_length=100_000)
    error_code: str | None = None
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EngineeringRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    provider_id: str
    provider_kind: ProviderKind
    workspace_kind: WorkspaceKind
    rounds: int = Field(ge=1)
    completed: bool
    changed_files: tuple[str, ...]
    tool_results: tuple[ToolResult, ...]
    final_message: str
    credentials_exposed: bool = False
    external_processing_used: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

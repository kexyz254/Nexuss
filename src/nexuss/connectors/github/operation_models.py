"""Validated read-only GitHub workspace control-plane contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA1 = r"^[0-9a-f]{40}$"
_SHA256 = r"^[0-9a-f]{64}$"
_FULL_NAME = r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"


class ReadOnlyOperation(StrEnum):
    ACCOUNT_INVENTORY = "account_inventory"
    REPOSITORY_SNAPSHOT = "repository_snapshot"
    SOURCE_ANALYSIS = "source_analysis"
    BUILD_PLAN = "build_plan"
    BUILD_EXECUTION = "build_execution"
    PULL_REQUEST_INSPECTION = "pull_request_inspection"
    ISSUE_INSPECTION = "issue_inspection"
    ACTIONS_INSPECTION = "actions_inspection"


class BuildExecutionMode(StrEnum):
    PLAN_ONLY = "plan_only"
    TRUSTED_LOCAL = "trusted_local"


class GitHubOrganizationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: int
    login: str
    html_url: str
    description: str | None = None


class GitHubInstallationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    permissions: dict[str, str] = Field(default_factory=dict)
    suspended: bool = False


class GitHubBranchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    commit_sha: str = Field(pattern=_SHA1)
    protected: bool = False


class GitHubTagSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    commit_sha: str = Field(pattern=_SHA1)


class GitHubCommitSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sha: str = Field(pattern=_SHA1)
    message: str
    author_name: str | None = None
    author_login: str | None = None
    authored_at: datetime | None = None
    html_url: str | None = None


class GitHubPullRequestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int = Field(ge=1)
    title: str
    state: str
    draft: bool = False
    author_login: str | None = None
    head_ref: str
    head_sha: str = Field(pattern=_SHA1)
    base_ref: str
    mergeable_state: str | None = None
    requested_reviewers: tuple[str, ...] = ()
    review_comments: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
    html_url: str


class GitHubIssueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int = Field(ge=1)
    title: str
    state: str
    author_login: str | None = None
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    milestone: str | None = None
    comments: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
    html_url: str


class GitHubWorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: int
    name: str
    path: str
    state: str
    html_url: str


class GitHubWorkflowRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: int
    workflow_id: int | None = None
    name: str
    event: str
    status: str
    conclusion: str | None = None
    branch: str | None = None
    head_sha: str = Field(pattern=_SHA1)
    attempt: int = Field(default=1, ge=1)
    actor_login: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    html_url: str


class GitHubWorkflowJobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: int
    run_id: int
    name: str
    status: str
    conclusion: str | None = None
    runner_name: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    html_url: str


class RepositorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_full_name: str = Field(pattern=_FULL_NAME)
    requested_ref: str = Field(default="main", min_length=1, max_length=255)

    @field_validator("requested_ref")
    @classmethod
    def safe_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized or normalized.startswith("-"):
            raise ValueError("requested_ref is invalid")
        if any(part in {".", ".."} for part in normalized.split("/")):
            raise ValueError("requested_ref contains an invalid path segment")
        return normalized


class RepositorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID = Field(default_factory=uuid4)
    account_login: str
    repository_id: int
    repository_full_name: str = Field(pattern=_FULL_NAME)
    requested_ref: str
    resolved_commit_sha: str = Field(pattern=_SHA1)
    archive_sha256: str = Field(pattern=_SHA256)
    manifest_sha256: str = Field(pattern=_SHA256)
    workspace_root: str
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    private_repository: bool
    read_only: bool = True
    credentials_exposed: bool = False
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def workspace_is_absolute(self) -> RepositorySnapshot:
        if not Path(self.workspace_root).is_absolute():
            raise ValueError("workspace_root must be absolute")
        return self


class SnapshotFileContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID
    repository_full_name: str = Field(pattern=_FULL_NAME)
    resolved_commit_sha: str = Field(pattern=_SHA1)
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_SHA256)
    content: str = Field(max_length=1_000_000)
    read_only: bool = True
    credentials_exposed: bool = False


class SourceLanguageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: str
    files: int = Field(ge=0)
    bytes: int = Field(ge=0)


class DependencyManifestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    ecosystem: str
    sha256: str = Field(pattern=_SHA256)


class SourceAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: UUID = Field(default_factory=uuid4)
    snapshot_id: UUID
    repository_full_name: str = Field(pattern=_FULL_NAME)
    resolved_commit_sha: str = Field(pattern=_SHA1)
    languages: tuple[SourceLanguageSummary, ...]
    build_systems: tuple[str, ...]
    dependency_manifests: tuple[DependencyManifestSummary, ...]
    likely_entry_points: tuple[str, ...]
    test_targets: tuple[str, ...]
    source_files: int = Field(ge=0)
    test_files: int = Field(ge=0)
    documentation_files: int = Field(ge=0)
    binary_files: int = Field(ge=0)
    oversized_files: tuple[str, ...] = ()
    architecture_hints: tuple[str, ...] = ()
    evidence_sha256: str = Field(pattern=_SHA256)
    credentials_exposed: bool = False
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BuildCommandPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    argv: tuple[str, ...]
    reason: str
    executes_repository_code: bool


class BuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID = Field(default_factory=uuid4)
    snapshot_id: UUID
    repository_full_name: str = Field(pattern=_FULL_NAME)
    resolved_commit_sha: str = Field(pattern=_SHA1)
    mode: BuildExecutionMode
    commands: tuple[BuildCommandPlan, ...]
    execution_allowed: bool
    execution_boundary: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BuildCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    argv: tuple[str, ...]
    exit_code: int
    output: str = Field(max_length=100_000)
    timed_out: bool = False
    output_sha256: str = Field(pattern=_SHA256)


class BuildRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    snapshot_id: UUID
    repository_full_name: str = Field(pattern=_FULL_NAME)
    resolved_commit_sha: str = Field(pattern=_SHA1)
    mode: BuildExecutionMode
    completed: bool
    commands: tuple[BuildCommandResult, ...]
    workspace_deleted: bool
    network_isolation_claimed: bool = False
    credentials_exposed: bool = False
    evidence_sha256: str = Field(pattern=_SHA256)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReadOnlyReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID = Field(default_factory=uuid4)
    operation: ReadOnlyOperation
    account_login: str
    repository_full_name: str | None = Field(default=None, pattern=_FULL_NAME)
    requested_ref: str | None = None
    resolved_commit_sha: str | None = Field(default=None, pattern=_SHA1)
    request_sha256: str = Field(pattern=_SHA256)
    evidence_sha256: str = Field(pattern=_SHA256)
    status: str
    summary: dict[str, object] = Field(default_factory=dict)
    github_write_performed: bool = False
    approval_required: bool = False
    credentials_exposed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def enforce_read_only(self) -> ReadOnlyReceipt:
        if self.github_write_performed or self.approval_required:
            raise ValueError("read-only receipts cannot represent an approved GitHub write")
        return self

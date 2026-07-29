"""Read-only GitHub Actions workflow, run, and job inspection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from nexuss.connectors.github.operation_models import (
    GitHubWorkflowJobSummary,
    GitHubWorkflowRunSummary,
    GitHubWorkflowSummary,
)


class ActionsReadApi(Protocol):
    def list_workflows(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubWorkflowSummary, ...]: ...

    def list_workflow_runs(
        self,
        owner: str,
        repository: str,
        *,
        limit: int = 50,
    ) -> tuple[GitHubWorkflowRunSummary, ...]: ...

    def list_workflow_jobs(
        self,
        owner: str,
        repository: str,
        run_id: int,
    ) -> tuple[GitHubWorkflowJobSummary, ...]: ...


class ActionsInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_full_name: str
    workflows: tuple[GitHubWorkflowSummary, ...]
    runs: tuple[GitHubWorkflowRunSummary, ...]
    jobs_by_run: dict[int, tuple[GitHubWorkflowJobSummary, ...]]
    failing_run_ids: tuple[int, ...]
    in_progress_run_ids: tuple[int, ...]
    github_write_performed: bool = False
    observed_at: datetime


class GitHubActionsMonitor:
    def inspect(
        self,
        api: ActionsReadApi,
        repository_full_name: str,
        *,
        include_jobs_for_runs: int = 10,
        now: datetime | None = None,
    ) -> ActionsInspection:
        owner, repository = repository_full_name.split("/", 1)
        workflows = api.list_workflows(owner, repository)
        runs = api.list_workflow_runs(owner, repository, limit=50)
        jobs: dict[int, tuple[GitHubWorkflowJobSummary, ...]] = {}
        for run in runs[: max(0, min(include_jobs_for_runs, 25))]:
            jobs[run.run_id] = api.list_workflow_jobs(
                owner,
                repository,
                run.run_id,
            )
        failing = tuple(
            run.run_id
            for run in runs
            if run.conclusion in {"failure", "timed_out", "cancelled", "action_required"}
        )
        in_progress = tuple(
            run.run_id
            for run in runs
            if run.status not in {"completed"}
        )
        return ActionsInspection(
            repository_full_name=repository_full_name,
            workflows=workflows,
            runs=runs,
            jobs_by_run=jobs,
            failing_run_ids=failing,
            in_progress_run_ids=in_progress,
            observed_at=now or datetime.now(UTC),
        )

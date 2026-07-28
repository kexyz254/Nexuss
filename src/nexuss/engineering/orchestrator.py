"""Bounded multi-round engineering orchestration."""

from __future__ import annotations

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import EngineeringRunReceipt, EngineeringTaskSpec, ToolResult
from nexuss.engineering.prompts import system_prompt, user_prompt
from nexuss.engineering.providers.base import ProviderRequest
from nexuss.engineering.router import EngineeringProviderRouter
from nexuss.engineering.tools import WorkspaceToolRegistry
from nexuss.engineering.workspace import IsolatedWorkspace


class EngineeringOrchestrator:
    def __init__(self, router: EngineeringProviderRouter) -> None:
        self._router = router

    def run(
        self,
        task: EngineeringTaskSpec,
        workspace: IsolatedWorkspace,
    ) -> EngineeringRunReceipt:
        registry = WorkspaceToolRegistry(workspace)
        results: list[ToolResult] = []
        final_message = ""

        for round_number in range(1, task.max_rounds + 1):
            proposal = self._router.propose(
                task,
                ProviderRequest(
                    system_prompt=system_prompt(),
                    user_prompt=user_prompt(task, tuple(results)),
                ),
            )

            if proposal.done:
                final_message = proposal.completion_message or proposal.summary
                profile = self._router.profile(task.provider_id)
                return EngineeringRunReceipt(
                    task_id=task.task_id,
                    provider_id=profile.provider_id,
                    provider_kind=profile.kind,
                    workspace_kind=task.workspace_kind,
                    rounds=round_number,
                    completed=True,
                    changed_files=workspace.changed_files,
                    tool_results=tuple(results),
                    final_message=final_message,
                    credentials_exposed=False,
                    external_processing_used=profile.external,
                )

            if not proposal.tool_requests:
                raise EngineeringError(
                    "ENGINEERING_PROVIDER_STALLED",
                    "The provider neither completed the task nor requested a tool.",
                )

            for request in proposal.tool_requests:
                if request.tool_name not in task.allowed_tools:
                    raise EngineeringError(
                        "ENGINEERING_TOOL_NOT_ALLOWED",
                        "The provider requested a tool outside the task contract.",
                    )
                results.append(registry.execute(request))
                if len(workspace.changed_files) > task.max_files_changed:
                    raise EngineeringError(
                        "ENGINEERING_FILE_BUDGET_EXCEEDED",
                        "The task exceeded its changed-file budget.",
                    )

        raise EngineeringError(
            "ENGINEERING_ROUND_LIMIT_EXCEEDED",
            "The engineering task exceeded its model-round budget.",
        )

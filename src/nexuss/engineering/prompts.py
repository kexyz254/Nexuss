"""Provider-independent engineering prompt construction."""

from __future__ import annotations

import json

from nexuss.engineering.models import EngineeringTaskSpec, ToolResult


def system_prompt() -> str:
    return (
        "You are a code proposal engine inside Nexuss. You do not execute tools, "
        "access credentials, publish changes, or widen permissions. Return exactly "
        "one JSON object with keys: summary, tool_requests, done, completion_message. "
        "Each tool request has request_id, tool_name, arguments, and rationale. "
        "Use only tools listed by Nexuss. Never request secrets, .env files, shell "
        "operators, credential files, network exfiltration, Git writes, or publication."
    )


def user_prompt(task: EngineeringTaskSpec, results: tuple[ToolResult, ...]) -> str:
    state = {
        "goal": task.goal,
        "sensitivity": task.sensitivity.value,
        "workspace_kind": task.workspace_kind.value,
        "allowed_tools": [item.value for item in task.allowed_tools],
        "limits": {
            "max_rounds": task.max_rounds,
            "max_files_changed": task.max_files_changed,
            "max_runtime_seconds": task.max_runtime_seconds,
        },
        "prior_tool_results": [result.model_dump(mode="json") for result in results[-20:]],
    }
    return json.dumps(state, sort_keys=True, ensure_ascii=False)

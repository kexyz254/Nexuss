"""Deterministic workspace tool registry."""

from __future__ import annotations

import hashlib
import json

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ToolName, ToolRequest, ToolResult
from nexuss.engineering.workspace import IsolatedWorkspace


class WorkspaceToolRegistry:
    def __init__(self, workspace: IsolatedWorkspace) -> None:
        self._workspace = workspace

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            output = self._execute(request)
            success = True
            error_code = None
        except EngineeringError as exc:
            output = exc.message
            success = False
            error_code = exc.code
        digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
        return ToolResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            success=success,
            output=output,
            error_code=error_code,
            evidence_sha256=digest,
        )

    def _execute(self, request: ToolRequest) -> str:
        arguments = request.arguments
        if request.tool_name is ToolName.READ_FILE:
            path = str(arguments.get("path", ""))
            content = self._workspace.read_text(path)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return json.dumps({"path": path, "sha256": digest, "content": content})

        if request.tool_name is ToolName.WRITE_FILE:
            path = str(arguments.get("path", ""))
            content = str(arguments.get("content", ""))
            expected = arguments.get("expected_sha256")
            digest = self._workspace.write_text(
                path,
                content,
                expected_sha256=str(expected) if expected else None,
            )
            return json.dumps({"path": path, "sha256": digest, "written": True})

        if request.tool_name is ToolName.LIST_FILES:
            path = str(arguments.get("path", "."))
            return json.dumps({"path": path, "files": self._workspace.list_files(path)})

        if request.tool_name is ToolName.RUN_COMMAND:
            raw = arguments.get("argv")
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise EngineeringError(
                    "ENGINEERING_COMMAND_INVALID",
                    "run_command requires a string argument vector.",
                )
            exit_code, output = self._workspace.run_command(raw)
            return json.dumps({"argv": raw, "exit_code": exit_code, "output": output})

        raise EngineeringError(
            "ENGINEERING_TOOL_UNKNOWN",
            "The requested engineering tool is not registered.",
        )

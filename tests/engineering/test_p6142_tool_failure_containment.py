from uuid import uuid4

import nexuss.engineering.prompt_build as prompt_build
from nexuss.engineering.models import ModelProposal, ToolName, ToolRequest


class _Workspace:
    root = None

    def __init__(self):
        self._changed = ()

    @property
    def changed_files(self):
        return self._changed


class _Agent:
    def __init__(self):
        self.phases = []

    def propose(self, *, goal, phase, context, allowed):
        del goal, context, allowed
        self.phases.append(phase)
        return ModelProposal(
            summary="bounded test proposal",
            tool_requests=(
                ToolRequest(
                    request_id=uuid4(),
                    tool_name=ToolName.READ_FILE,
                    arguments={"path": "src/nexuss/ui/app.js"},
                    rationale="exercise contained tool failure",
                ),
            ),
            done=False,
        )


class _Progress:
    def __init__(self):
        self.events = []

    def emit(self, **event):
        self.events.append(event)


def test_unexpected_tool_failure_is_contained_and_write_required_is_reached(monkeypatch):
    workspace = _Workspace()
    agent = _Agent()
    progress = _Progress()

    def explode(*args, **kwargs):
        raise RuntimeError("simulated isolated tool failure")

    monkeypatch.setattr(prompt_build, "_execute_requests", explode)
    monkeypatch.setattr(prompt_build, "_MAX_MODEL_ROUNDS", 6)

    rounds, recent = prompt_build._build_with_agent(
        goal="small bounded test",
        workspace=workspace,
        agent=agent,
        progress=progress,
    )

    assert rounds == 6
    assert agent.phases == [
        "discovery",
        "discovery",
        "implementation",
        "implementation",
        "write_required",
        "write_required",
    ]
    assert any(
        item.get("error_code") == "ENGINEERING_TOOL_REQUEST_FAILURE"
        for item in recent
        if isinstance(item, dict)
    )
    assert any(
        event.get("code") == "ENGINEERING_TOOL_REQUEST_FAILURE"
        for event in progress.events
    )

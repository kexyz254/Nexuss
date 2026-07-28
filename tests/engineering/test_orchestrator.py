from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from nexuss.engineering.models import (
    EngineeringTaskSpec,
    ModelProposal,
    ProviderKind,
    TaskSensitivity,
    ToolName,
    ToolRequest,
)
from nexuss.engineering.orchestrator import EngineeringOrchestrator
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.router import EngineeringProviderRouter
from nexuss.engineering.workspace import IsolatedWorkspace


class FakeProvider:
    def __init__(self) -> None:
        self.profile = ProviderProfile(
            provider_id="local-test",
            kind=ProviderKind.LOCAL,
            model="fixture",
            api_base="local://fixture",
            external=False,
        )
        self.calls = 0

    def propose(self, _request):
        self.calls += 1
        if self.calls == 1:
            return ModelProposal(
                summary="Create two landing page files.",
                tool_requests=(
                    ToolRequest(
                        request_id=uuid4(),
                        tool_name=ToolName.WRITE_FILE,
                        arguments={"path": "index.html", "content": "<h1>Nexuss</h1>"},
                        rationale="Create semantic entry page.",
                    ),
                    ToolRequest(
                        request_id=uuid4(),
                        tool_name=ToolName.WRITE_FILE,
                        arguments={"path": "styles.css", "content": "body { font-family: sans-serif; }"},
                        rationale="Create professional base styling.",
                    ),
                ),
            )
        return ModelProposal(
            summary="Landing page prepared.",
            done=True,
            completion_message="Created and verified the bounded landing-page workspace.",
        )


def test_orchestrator_executes_bounded_model_requests(tmp_path: Path) -> None:
    provider = FakeProvider()
    router = EngineeringProviderRouter((provider,))
    orchestrator = EngineeringOrchestrator(router)
    workspace = IsolatedWorkspace(tmp_path / "workspace")
    task = EngineeringTaskSpec(
        goal="Create a simple Nexuss landing page.",
        provider_id="local-test",
        sensitivity=TaskSensitivity.PRIVATE,
    )

    receipt = orchestrator.run(task, workspace)

    assert receipt.completed
    assert receipt.rounds == 2
    assert receipt.changed_files == ("index.html", "styles.css")
    assert receipt.credentials_exposed is False
    assert workspace.read_text("index.html") == "<h1>Nexuss</h1>"

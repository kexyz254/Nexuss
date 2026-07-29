from __future__ import annotations

from pathlib import Path

import pytest

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.lifecycle import (
    EngineeringArtifactValidator,
    EngineeringTaskLifecycle,
)
from nexuss.engineering.models import (
    EngineeringRunReceipt,
    EngineeringTaskSpec,
    ProviderKind,
    WorkspaceKind,
)
from nexuss.engineering.provider_connections import (
    ProviderAccessCode,
    ProviderAccessDecision,
)
from nexuss.engineering.publication import (
    EngineeringPublicationPlanner,
)
from nexuss.engineering.workspace import IsolatedWorkspace


def _review(tmp_path: Path):
    task = EngineeringTaskSpec(
        goal="Create a text file.",
        provider_id="local",
    )
    access = ProviderAccessDecision(
        provider_id="local",
        provider_kind=ProviderKind.LOCAL,
        available=True,
        code=ProviderAccessCode.READY,
        user_message="ready",
        model="local-test",
        identity_verified=True,
        billing_ready=True,
        credential_present=False,
    )

    def executor(
        task: EngineeringTaskSpec,
        workspace: IsolatedWorkspace,
    ) -> EngineeringRunReceipt:
        workspace.write_text("index.html", "<main>Hello</main>")
        return EngineeringRunReceipt(
            task_id=task.task_id,
            provider_id="local",
            provider_kind=ProviderKind.LOCAL,
            workspace_kind=WorkspaceKind.LOCAL,
            rounds=1,
            completed=True,
            changed_files=workspace.changed_files,
            tool_results=(),
            final_message="complete",
            credentials_exposed=False,
            external_processing_used=False,
        )

    outcome = EngineeringTaskLifecycle(
        validator=EngineeringArtifactValidator()
    ).execute(
        task,
        access,
        executor,
        lambda: IsolatedWorkspace(
            tmp_path / "workspace"
        ),
    )
    assert outcome.review is not None
    return outcome.review


def test_publication_payload_is_exact_and_nonexecuting(
    tmp_path: Path,
) -> None:
    review = _review(tmp_path)

    proposal = EngineeringPublicationPlanner.prepare_github(
        review,
        account_login="kexyz254",
        repository_name="Nexuss-AI",
        branch="main",
        commit_message="feat: add landing page",
    )

    assert proposal.approval_required is True
    assert proposal.approval_channel == "phone"
    assert proposal.github_changed is False
    assert proposal.published is False
    assert proposal.force_push is False
    assert len(proposal.payload_sha256) == 64
    assert proposal.files[0].path == "index.html"


def test_publication_hash_changes_with_commit_message(
    tmp_path: Path,
) -> None:
    review = _review(tmp_path)

    first = EngineeringPublicationPlanner.prepare_github(
        review,
        account_login="kexyz254",
        repository_name="Nexuss-AI",
        branch="main",
        commit_message="feat: first",
    )
    second = EngineeringPublicationPlanner.prepare_github(
        review,
        account_login="kexyz254",
        repository_name="Nexuss-AI",
        branch="main",
        commit_message="feat: second",
    )

    assert first.payload_sha256 != second.payload_sha256


def test_workflow_publication_is_prohibited(
    tmp_path: Path,
) -> None:
    task = EngineeringTaskSpec(
        goal="Create workflow.",
        provider_id="local",
    )
    access = ProviderAccessDecision(
        provider_id="local",
        provider_kind=ProviderKind.LOCAL,
        available=True,
        code=ProviderAccessCode.READY,
        user_message="ready",
        model="local-test",
        identity_verified=True,
        billing_ready=True,
        credential_present=False,
    )

    def executor(
        task: EngineeringTaskSpec,
        workspace: IsolatedWorkspace,
    ) -> EngineeringRunReceipt:
        workspace.write_text(
            ".github/workflows/build.yml",
            "name: build",
        )
        return EngineeringRunReceipt(
            task_id=task.task_id,
            provider_id="local",
            provider_kind=ProviderKind.LOCAL,
            workspace_kind=WorkspaceKind.LOCAL,
            rounds=1,
            completed=True,
            changed_files=workspace.changed_files,
            tool_results=(),
            final_message="complete",
            credentials_exposed=False,
            external_processing_used=False,
        )

    outcome = EngineeringTaskLifecycle().execute(
        task,
        access,
        executor,
        lambda: IsolatedWorkspace(
            tmp_path / "workspace"
        ),
    )
    assert outcome.review is not None

    with pytest.raises(EngineeringError) as captured:
        EngineeringPublicationPlanner.prepare_github(
            outcome.review,
            account_login="kexyz254",
            repository_name="Nexuss-AI",
            branch="main",
            commit_message="ci: add workflow",
        )

    assert captured.value.code == (
        "ENGINEERING_WORKFLOW_WRITE_PROHIBITED"
    )

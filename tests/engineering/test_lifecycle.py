from __future__ import annotations

from pathlib import Path

from nexuss.engineering.lifecycle import (
    EngineeringArtifactValidator,
    EngineeringLifecycleState,
    EngineeringTaskLifecycle,
    EngineeringValidationPolicy,
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
from nexuss.engineering.workspace import IsolatedWorkspace


def _access(
    *,
    available: bool,
) -> ProviderAccessDecision:
    return ProviderAccessDecision(
        provider_id="deepseek",
        provider_kind=ProviderKind.DEEPSEEK,
        available=available,
        optional=True,
        code=(
            ProviderAccessCode.READY
            if available
            else ProviderAccessCode.INSUFFICIENT_BALANCE
        ),
        user_message=(
            "ready"
            if available
            else "Pay for DeepSeek API access."
        ),
        model="deepseek-v4-pro",
        identity_verified=True,
        billing_ready=available,
        credential_present=True,
    )


def _receipt(
    task: EngineeringTaskSpec,
    workspace: IsolatedWorkspace,
) -> EngineeringRunReceipt:
    workspace.write_text(
        "index.html",
        (
            "<!doctype html><title>Nexuss</title>"
            '<link rel="stylesheet" href="styles.css">'
            "<main><h1>Nexuss</h1></main>"
        ),
    )
    workspace.write_text(
        "styles.css",
        "body { margin: 0; }",
    )
    return EngineeringRunReceipt(
        task_id=task.task_id,
        provider_id="deepseek",
        provider_kind=ProviderKind.DEEPSEEK,
        workspace_kind=WorkspaceKind.LOCAL,
        rounds=1,
        completed=True,
        changed_files=workspace.changed_files,
        tool_results=(),
        final_message="complete",
        credentials_exposed=False,
        external_processing_used=True,
    )


def test_unpaid_provider_does_not_create_workspace(
    tmp_path: Path,
) -> None:
    task = EngineeringTaskSpec(
        goal="Create a landing page.",
        provider_id="deepseek",
    )
    called = False

    def factory() -> IsolatedWorkspace:
        nonlocal called
        called = True
        return IsolatedWorkspace(tmp_path / "workspace")

    outcome = EngineeringTaskLifecycle().execute(
        task,
        _access(available=False),
        _receipt,
        factory,
    )

    assert called is False
    assert outcome.state is (
        EngineeringLifecycleState.PROVIDER_BLOCKED
    )
    assert outcome.workspace_created is False
    assert outcome.github_changed is False


def test_validated_run_reaches_review_ready(
    tmp_path: Path,
) -> None:
    task = EngineeringTaskSpec(
        goal="Create a landing page.",
        provider_id="deepseek",
    )
    validator = EngineeringArtifactValidator(
        EngineeringValidationPolicy(
            require_landing_page_contract=True,
            block_external_web_references=True,
        )
    )
    outcome = EngineeringTaskLifecycle(
        validator=validator
    ).execute(
        task,
        _access(available=True),
        _receipt,
        lambda: IsolatedWorkspace(
            tmp_path / "workspace"
        ),
    )

    assert outcome.state is (
        EngineeringLifecycleState.REVIEW_READY
    )
    assert outcome.review is not None
    assert outcome.review.validation.passed is True
    assert outcome.review.publication_allowed is True
    assert "+++ b/index.html" in outcome.review.exact_diff
    assert outcome.github_changed is False


def test_secret_detection_blocks_publication(
    tmp_path: Path,
) -> None:
    task = EngineeringTaskSpec(
        goal="Create a file.",
        provider_id="deepseek",
    )

    def executor(
        task: EngineeringTaskSpec,
        workspace: IsolatedWorkspace,
    ) -> EngineeringRunReceipt:
        workspace.write_text(
            "notes.txt",
            "Authorization: Bearer secret-token-value",
        )
        return EngineeringRunReceipt(
            task_id=task.task_id,
            provider_id="deepseek",
            provider_kind=ProviderKind.DEEPSEEK,
            workspace_kind=WorkspaceKind.LOCAL,
            rounds=1,
            completed=True,
            changed_files=workspace.changed_files,
            tool_results=(),
            final_message="complete",
            credentials_exposed=False,
            external_processing_used=True,
        )

    outcome = EngineeringTaskLifecycle().execute(
        task,
        _access(available=True),
        executor,
        lambda: IsolatedWorkspace(
            tmp_path / "workspace"
        ),
    )

    assert outcome.state is EngineeringLifecycleState.FAILED
    assert outcome.review is not None
    assert outcome.review.validation.passed is False
    assert outcome.review.publication_allowed is False
    assert outcome.github_changed is False


def test_events_are_sequential(
    tmp_path: Path,
) -> None:
    task = EngineeringTaskSpec(
        goal="Create a landing page.",
        provider_id="deepseek",
    )
    outcome = EngineeringTaskLifecycle().execute(
        task,
        _access(available=True),
        _receipt,
        lambda: IsolatedWorkspace(
            tmp_path / "workspace"
        ),
    )

    assert [event.sequence for event in outcome.events] == list(
        range(1, len(outcome.events) + 1)
    )

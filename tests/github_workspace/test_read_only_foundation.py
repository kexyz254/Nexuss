from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nexuss.connectors.github.actions_monitor import GitHubActionsMonitor
from nexuss.connectors.github.build_runner import BuildExecutionDenied, GitHubBuildRunner
from nexuss.connectors.github.event_store import ReadOnlyReceiptStore
from nexuss.connectors.github.models import GitHubRepository
from nexuss.connectors.github.operation_models import (
    BuildExecutionMode,
    GitHubCommitSummary,
    GitHubWorkflowRunSummary,
    ReadOnlyOperation,
    ReadOnlyReceipt,
    RepositorySelection,
)
from nexuss.connectors.github.pull_request_manager import GitHubPullRequestManager
from nexuss.connectors.github.repository_analyzer import GitHubRepositoryAnalyzer
from nexuss.connectors.github.repository_workspace import (
    GitHubRepositoryWorkspace,
    RepositoryWorkspaceError,
)


class FakeArchiveApi:
    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.repository = GitHubRepository(
            repository_id=7,
            node_id="R7",
            name="demo",
            full_name="kexyz254/demo",
            owner_login="kexyz254",
            private=True,
            html_url="https://github.com/kexyz254/demo",
            api_url="https://api.github.com/repos/kexyz254/demo",
            default_branch="main",
        )
        self.commit = GitHubCommitSummary(
            sha="a" * 40,
            message="initial",
            author_name="Peter",
            authored_at=datetime.now(UTC),
        )

    def get_repository(self, owner: str, repository: str):
        assert owner == "kexyz254"
        assert repository == "demo"
        return self.repository

    def resolve_commit(self, owner: str, repository: str, ref: str):
        assert ref == "main"
        return self.commit

    def download_repository_zipball(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
        *,
        max_bytes: int,
    ) -> bytes:
        assert commit_sha == self.commit.sha
        assert len(self.archive) < max_bytes
        return self.archive


def make_zip(files: dict[str, bytes | str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_read_only_receipt_refuses_write_claim() -> None:
    with pytest.raises(ValueError):
        ReadOnlyReceipt(
            operation=ReadOnlyOperation.ACCOUNT_INVENTORY,
            account_login="kexyz254",
            request_sha256="1" * 64,
            evidence_sha256="2" * 64,
            status="bad",
            github_write_performed=True,
        )


def test_repository_selection_rejects_unsafe_ref() -> None:
    with pytest.raises(ValueError):
        RepositorySelection(
            repository_full_name="kexyz254/demo",
            requested_ref="../main",
        )


def test_workspace_creates_immutable_verified_snapshot(tmp_path: Path) -> None:
    archive = make_zip(
        {
            "kexyz254-demo-abcdef/src/main.py": "print('hello')\n",
            "kexyz254-demo-abcdef/tests/test_main.py": "def test_ok(): assert True\n",
            "kexyz254-demo-abcdef/pyproject.toml": "[project]\nname='demo'\n",
        }
    )
    workspace = GitHubRepositoryWorkspace(tmp_path / "snapshots")
    selection = RepositorySelection(
        repository_full_name="kexyz254/demo",
        requested_ref="main",
    )

    snapshot = workspace.create_snapshot(
        FakeArchiveApi(archive),
        selection,
        account_login="kexyz254",
    )

    root = Path(snapshot.workspace_root)
    assert snapshot.file_count == 3
    assert snapshot.read_only is True
    assert snapshot.credentials_exposed is False
    assert (root / "src/main.py").read_text() == "print('hello')\n"
    assert (root / "NEXUSS-SNAPSHOT.json").is_file()
    assert workspace.get_snapshot(snapshot.snapshot_id) == snapshot

    second = workspace.create_snapshot(
        FakeArchiveApi(archive),
        selection,
        account_login="kexyz254",
    )
    assert second.snapshot_id == snapshot.snapshot_id


def test_workspace_rejects_path_traversal(tmp_path: Path) -> None:
    archive = make_zip(
        {
            "root/good.txt": "good",
            "root/../../escape.txt": "bad",
        }
    )
    workspace = GitHubRepositoryWorkspace(tmp_path / "snapshots")

    with pytest.raises(RepositoryWorkspaceError) as captured:
        workspace.create_snapshot(
            FakeArchiveApi(archive),
            RepositorySelection(
                repository_full_name="kexyz254/demo",
                requested_ref="main",
            ),
            account_login="kexyz254",
        )

    assert captured.value.code == "GITHUB_WORKSPACE_ARCHIVE_PATH_INVALID"


def test_analyzer_inventory_and_build_plan(tmp_path: Path, monkeypatch) -> None:
    archive = make_zip(
        {
            "root/src/main.py": "print('hello')\n",
            "root/tests/test_main.py": "def test_ok(): assert True\n",
            "root/pyproject.toml": "[project]\nname='demo'\n",
            "root/README.md": "# Demo\n",
        }
    )
    workspace = GitHubRepositoryWorkspace(tmp_path / "snapshots")
    snapshot = workspace.create_snapshot(
        FakeArchiveApi(archive),
        RepositorySelection(
            repository_full_name="kexyz254/demo",
            requested_ref="main",
        ),
        account_login="kexyz254",
    )
    analysis = GitHubRepositoryAnalyzer().analyze(snapshot)

    assert analysis.source_files == 2
    assert analysis.test_files == 1
    assert analysis.documentation_files == 1
    assert analysis.languages[0].language == "Python"
    assert "Python packaging" in analysis.build_systems
    assert "src/main.py" in analysis.likely_entry_points

    monkeypatch.delenv("NEXUSS_GITHUB_WORKSPACE_TRUSTED_LOCAL", raising=False)
    plan = GitHubBuildRunner().plan(snapshot, analysis)
    assert plan.mode is BuildExecutionMode.PLAN_ONLY
    assert plan.execution_allowed is False
    assert any(item.label == "python-tests" for item in plan.commands)

    with pytest.raises(BuildExecutionDenied):
        GitHubBuildRunner().execute(snapshot, plan)


def test_receipt_store_round_trip(tmp_path: Path) -> None:
    store = ReadOnlyReceiptStore(tmp_path / "receipts")
    receipt = ReadOnlyReceipt(
        operation=ReadOnlyOperation.SOURCE_ANALYSIS,
        account_login="kexyz254",
        repository_full_name="kexyz254/demo",
        requested_ref="main",
        resolved_commit_sha="a" * 40,
        request_sha256="1" * 64,
        evidence_sha256="2" * 64,
        status="verified_read_only",
    )
    path = store.put(receipt)

    assert path.is_file()
    assert store.get(receipt.receipt_id) == receipt
    assert store.list_recent(limit=1) == (receipt,)


class FakeReviewApi:
    def list_pull_requests(self, owner, repository, *, state="open", limit=50):
        return ()

    def list_issues(self, owner, repository, *, state="open", limit=50):
        return ()

    def list_workflows(self, owner, repository):
        return ()

    def list_workflow_runs(self, owner, repository, *, limit=50):
        return (
            GitHubWorkflowRunSummary(
                run_id=9,
                name="CI",
                event="push",
                status="completed",
                conclusion="failure",
                head_sha="b" * 40,
                html_url="https://github.com/kexyz254/demo/actions/runs/9",
            ),
        )

    def list_workflow_jobs(self, owner, repository, run_id):
        return ()


def test_pr_issue_and_actions_are_read_only() -> None:
    manager = GitHubPullRequestManager()
    pulls = manager.inspect_pull_requests(FakeReviewApi(), "kexyz254/demo")
    issues = manager.inspect_issues(FakeReviewApi(), "kexyz254/demo")
    actions = GitHubActionsMonitor().inspect(FakeReviewApi(), "kexyz254/demo")

    assert pulls.github_write_performed is False
    assert issues.github_write_performed is False
    assert actions.github_write_performed is False
    assert actions.failing_run_ids == (9,)

from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from nexuss.connectors.github.event_store import ReadOnlyReceiptStore
from nexuss.connectors.github.models import GitHubAccount, GitHubRepository
from nexuss.connectors.github.operation_models import (
    GitHubBranchSummary,
    GitHubCommitSummary,
    GitHubWorkflowRunSummary,
    RepositorySelection,
)
from nexuss.connectors.github.repository_workspace import GitHubRepositoryWorkspace
from nexuss.connectors.github.workspace_control import GitHubWorkspaceControlPlane


class FakeReadApi:
    def __init__(self) -> None:
        self.account = GitHubAccount(
            account_id=1,
            login="kexyz254",
            account_type="User",
            html_url="https://github.com/kexyz254",
        )
        self.repository = GitHubRepository(
            repository_id=7,
            node_id="R7",
            name="GlyphSentry-Core-Final",
            full_name="kexyz254/GlyphSentry-Core-Final",
            owner_login="kexyz254",
            private=True,
            html_url="https://github.com/kexyz254/GlyphSentry-Core-Final",
            api_url="https://api.github.com/repos/kexyz254/GlyphSentry-Core-Final",
            default_branch="main",
            permissions={"pull": True, "push": True, "admin": True},
        )
        self.commit = GitHubCommitSummary(
            sha="a" * 40,
            message="Initial verified snapshot",
            author_name="Peter",
            authored_at=datetime.now(UTC),
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "kexyz254-GlyphSentry-Core-Final-aaaa/src/main.py",
                "def main():\n    return 'GlyphSentry'\n",
            )
            archive.writestr(
                "kexyz254-GlyphSentry-Core-Final-aaaa/tests/test_main.py",
                "def test_main():\n    assert True\n",
            )
            archive.writestr(
                "kexyz254-GlyphSentry-Core-Final-aaaa/pyproject.toml",
                "[project]\nname='glyphsentry'\nversion='1.0.0'\n",
            )
            archive.writestr(
                "kexyz254-GlyphSentry-Core-Final-aaaa/README.md",
                "# GlyphSentry Core\n",
            )
        self.archive = output.getvalue()

    def authenticated_user(self):
        return self.account

    def list_repositories(self, *, max_pages=10):
        return (self.repository,)

    def list_organizations(self):
        return ()

    def list_user_installations(self):
        return ()

    def get_repository(self, owner, repository):
        return self.repository

    def resolve_commit(self, owner, repository, ref):
        return self.commit

    def list_branches(self, owner, repository):
        return (
            GitHubBranchSummary(
                name="main",
                commit_sha=self.commit.sha,
                protected=True,
            ),
        )

    def list_tags(self, owner, repository):
        return ()

    def list_commits(self, owner, repository, *, ref=None, limit=50):
        return (self.commit,)

    def download_repository_zipball(
        self,
        owner,
        repository,
        commit_sha,
        *,
        max_bytes,
    ):
        return self.archive

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
                conclusion="success",
                head_sha=self.commit.sha,
                html_url=(
                    "https://github.com/kexyz254/"
                    "GlyphSentry-Core-Final/actions/runs/9"
                ),
            ),
        )

    def list_workflow_jobs(self, owner, repository, run_id):
        return ()


class FakeConnector:
    def __init__(self, api: FakeReadApi) -> None:
        self.api = api

    def read_only_api(self):
        return self.api


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="nexuss-p66a-demo-"))
    api = FakeReadApi()
    plane = GitHubWorkspaceControlPlane(
        connector=FakeConnector(api),
        workspace=GitHubRepositoryWorkspace(root / "snapshots"),
        receipts=ReadOnlyReceiptStore(root / "receipts"),
    )
    selection = RepositorySelection(
        repository_full_name="kexyz254/GlyphSentry-Core-Final",
        requested_ref="main",
    )

    account = plane.inspect_account()
    repository = plane.inspect_repository(selection)
    snapshot = plane.create_snapshot(selection)
    analysis = plane.analyze_snapshot(snapshot.snapshot_id)
    build_plan = plane.create_build_plan(snapshot.snapshot_id)
    pulls = plane.inspect_pull_requests(selection.repository_full_name)
    issues = plane.inspect_issues(selection.repository_full_name)
    actions = plane.inspect_actions(selection.repository_full_name)
    receipts = plane.list_receipts()

    print()
    print("=" * 76)
    print("NEXUSS P6.6A GITHUB WORKSPACE READ-ONLY MOCK")
    print("=" * 76)
    print(f"Account verified:       {account.account.login}")
    print(f"Repositories visible:   {account.repository_inventory.total}")
    print(f"Repository selected:    {repository.repository.full_name}")
    print(f"Starting commit:        {snapshot.resolved_commit_sha}")
    print(f"Snapshot files:         {snapshot.file_count}")
    print(f"Manifest verified:      {bool(snapshot.manifest_sha256)}")
    print(f"Languages detected:     {len(analysis.languages)}")
    print(f"Test targets detected:  {analysis.test_files}")
    print(f"Build mode:             {build_plan.mode}")
    print(f"Build execution allowed:{build_plan.execution_allowed}")
    print(f"Pull requests read:     {len(pulls.pull_requests)}")
    print(f"Issues read:            {len(issues.issues)}")
    print(f"Actions runs read:      {len(actions.runs)}")
    print(f"Durable receipts:       {len(receipts)}")
    print("GitHub write performed: False")
    print("Phone approval required:False")
    print("Modification enabled:   False")
    print("Webhook enabled:        False")
    print("Credentials exposed:    False")
    print("Live GitHub contacted:  False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

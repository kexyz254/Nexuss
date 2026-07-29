"""Read-only GitHub Workspace Control Plane coordinator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from nexuss.connectors.github.account_intelligence import (
    GitHubAccountIntelligence,
    GitHubAccountIntelligenceReport,
)
from nexuss.connectors.github.actions_monitor import (
    ActionsInspection,
    GitHubActionsMonitor,
)
from nexuss.connectors.github.build_runner import GitHubBuildRunner
from nexuss.connectors.github.event_store import ReadOnlyReceiptStore
from nexuss.connectors.github.operation_models import (
    BuildPlan,
    BuildRunReceipt,
    ReadOnlyOperation,
    ReadOnlyReceipt,
    RepositorySelection,
    RepositorySnapshot,
    SnapshotFileContent,
    SourceAnalysisReport,
)
from nexuss.connectors.github.pull_request_manager import (
    GitHubPullRequestManager,
    IssueInspection,
    PullRequestInspection,
)
from nexuss.connectors.github.repository_analyzer import GitHubRepositoryAnalyzer
from nexuss.connectors.github.repository_reader import (
    GitHubRepositoryReader,
    RepositoryReadReport,
)
from nexuss.connectors.github.repository_workspace import GitHubRepositoryWorkspace


class GitHubWorkspaceControlPlane:
    def __init__(
        self,
        *,
        connector,
        workspace: GitHubRepositoryWorkspace,
        receipts: ReadOnlyReceiptStore,
    ) -> None:
        self._connector = connector
        self._workspace = workspace
        self._receipts = receipts
        self._account = GitHubAccountIntelligence()
        self._reader = GitHubRepositoryReader()
        self._analyzer = GitHubRepositoryAnalyzer()
        self._builds = GitHubBuildRunner()
        self._pulls = GitHubPullRequestManager()
        self._actions = GitHubActionsMonitor()

    @classmethod
    def from_environment(cls) -> GitHubWorkspaceControlPlane:
        from nexuss.connectors.github.runtime import get_github_connector

        return cls(
            connector=get_github_connector(),
            workspace=GitHubRepositoryWorkspace.from_environment(),
            receipts=ReadOnlyReceiptStore.from_environment(),
        )

    def inspect_account(self) -> GitHubAccountIntelligenceReport:
        api = self._connector.read_only_api()
        report = self._account.inspect(api)
        self._record(
            ReadOnlyOperation.ACCOUNT_INVENTORY,
            account_login=report.account.login,
            request={"operation": "account_inventory"},
            evidence_sha256=report.evidence_sha256,
            summary={
                "repositories": report.repository_inventory.total,
                "organizations": len(report.organizations),
                "installations": len(report.installations),
            },
        )
        return report

    def inspect_repository(
        self,
        selection: RepositorySelection,
    ) -> RepositoryReadReport:
        api = self._connector.read_only_api()
        account = api.authenticated_user()
        report = self._reader.inspect(
            api,
            selection,
            account_login=account.login,
        )
        evidence = self._model_sha256(report)
        self._record(
            ReadOnlyOperation.REPOSITORY_SNAPSHOT,
            account_login=account.login,
            repository_full_name=selection.repository_full_name,
            requested_ref=selection.requested_ref,
            resolved_commit_sha=report.resolved_commit.sha,
            request=selection.model_dump(mode="json"),
            evidence_sha256=evidence,
            summary={
                "branches": len(report.branches),
                "tags": len(report.tags),
                "commits": len(report.recent_commits),
                "metadata_only": True,
            },
        )
        return report

    def create_snapshot(
        self,
        selection: RepositorySelection,
    ) -> RepositorySnapshot:
        api = self._connector.read_only_api()
        account = api.authenticated_user()
        snapshot = self._workspace.create_snapshot(
            api,
            selection,
            account_login=account.login,
        )
        self._record(
            ReadOnlyOperation.REPOSITORY_SNAPSHOT,
            account_login=account.login,
            repository_full_name=snapshot.repository_full_name,
            requested_ref=snapshot.requested_ref,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            request=selection.model_dump(mode="json"),
            evidence_sha256=snapshot.manifest_sha256,
            summary={
                "snapshot_id": str(snapshot.snapshot_id),
                "files": snapshot.file_count,
                "bytes": snapshot.total_bytes,
                "archive_sha256": snapshot.archive_sha256,
                "manifest_sha256": snapshot.manifest_sha256,
                "read_only": True,
            },
        )
        return snapshot

    def read_snapshot_file(
        self,
        snapshot_id: UUID,
        relative_path: str,
    ) -> SnapshotFileContent:
        snapshot = self._workspace.get_snapshot(snapshot_id)
        root = Path(snapshot.workspace_root).resolve()
        if not relative_path or "\x00" in relative_path:
            raise ValueError("Snapshot file path is invalid")
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Snapshot file path escapes the repository") from exc
        if not candidate.is_file() or candidate.name == "NEXUSS-SNAPSHOT.json":
            raise FileNotFoundError(relative_path)
        size = candidate.stat().st_size
        if size > 1_000_000:
            raise ValueError("Snapshot file exceeds the one-megabyte read limit")
        raw = candidate.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Binary snapshot files are not returned as text") from exc
        result = SnapshotFileContent(
            snapshot_id=snapshot.snapshot_id,
            repository_full_name=snapshot.repository_full_name,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            path=candidate.relative_to(root).as_posix(),
            size_bytes=size,
            sha256=hashlib.sha256(raw).hexdigest(),
            content=content,
        )
        self._record(
            ReadOnlyOperation.SOURCE_ANALYSIS,
            account_login=snapshot.account_login,
            repository_full_name=snapshot.repository_full_name,
            requested_ref=snapshot.requested_ref,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            request={
                "snapshot_id": str(snapshot_id),
                "path": result.path,
            },
            evidence_sha256=result.sha256,
            summary={
                "path": result.path,
                "size_bytes": result.size_bytes,
                "sha256": result.sha256,
                "content_persisted_in_receipt": False,
            },
        )
        return result

    def analyze_snapshot(self, snapshot_id: UUID) -> SourceAnalysisReport:
        snapshot = self._workspace.get_snapshot(snapshot_id)
        report = self._analyzer.analyze(snapshot)
        self._record(
            ReadOnlyOperation.SOURCE_ANALYSIS,
            account_login=snapshot.account_login,
            repository_full_name=snapshot.repository_full_name,
            requested_ref=snapshot.requested_ref,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            request={"snapshot_id": str(snapshot_id)},
            evidence_sha256=report.evidence_sha256,
            summary={
                "languages": len(report.languages),
                "source_files": report.source_files,
                "test_files": report.test_files,
                "build_systems": list(report.build_systems),
                "entry_points": list(report.likely_entry_points[:25]),
            },
        )
        return report

    def create_build_plan(self, snapshot_id: UUID) -> BuildPlan:
        snapshot = self._workspace.get_snapshot(snapshot_id)
        analysis = self._analyzer.analyze(snapshot)
        plan = self._builds.plan(snapshot, analysis)
        evidence = self._model_sha256(plan)
        self._record(
            ReadOnlyOperation.BUILD_PLAN,
            account_login=snapshot.account_login,
            repository_full_name=snapshot.repository_full_name,
            requested_ref=snapshot.requested_ref,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            request={"snapshot_id": str(snapshot_id)},
            evidence_sha256=evidence,
            summary={
                "plan_id": str(plan.plan_id),
                "mode": plan.mode,
                "execution_allowed": plan.execution_allowed,
                "commands": [item.label for item in plan.commands],
                "boundary": plan.execution_boundary,
            },
        )
        return plan

    def execute_build(self, snapshot_id: UUID) -> BuildRunReceipt:
        snapshot = self._workspace.get_snapshot(snapshot_id)
        analysis = self._analyzer.analyze(snapshot)
        plan = self._builds.plan(snapshot, analysis)
        receipt = self._builds.execute(snapshot, plan)
        self._record(
            ReadOnlyOperation.BUILD_EXECUTION,
            account_login=snapshot.account_login,
            repository_full_name=snapshot.repository_full_name,
            requested_ref=snapshot.requested_ref,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            request={"snapshot_id": str(snapshot_id), "plan_id": str(plan.plan_id)},
            evidence_sha256=receipt.evidence_sha256,
            summary={
                "run_id": str(receipt.run_id),
                "completed": receipt.completed,
                "commands": len(receipt.commands),
                "workspace_deleted": receipt.workspace_deleted,
                "network_isolation_claimed": receipt.network_isolation_claimed,
            },
        )
        return receipt

    def inspect_pull_requests(
        self,
        repository_full_name: str,
        *,
        state: str = "open",
    ) -> PullRequestInspection:
        api = self._connector.read_only_api()
        account = api.authenticated_user()
        report = self._pulls.inspect_pull_requests(
            api,
            repository_full_name,
            state=state,
        )
        self._record(
            ReadOnlyOperation.PULL_REQUEST_INSPECTION,
            account_login=account.login,
            repository_full_name=repository_full_name,
            request={"repository": repository_full_name, "state": state},
            evidence_sha256=self._model_sha256(report),
            summary={"pull_requests": len(report.pull_requests)},
        )
        return report

    def inspect_issues(
        self,
        repository_full_name: str,
        *,
        state: str = "open",
    ) -> IssueInspection:
        api = self._connector.read_only_api()
        account = api.authenticated_user()
        report = self._pulls.inspect_issues(
            api,
            repository_full_name,
            state=state,
        )
        self._record(
            ReadOnlyOperation.ISSUE_INSPECTION,
            account_login=account.login,
            repository_full_name=repository_full_name,
            request={"repository": repository_full_name, "state": state},
            evidence_sha256=self._model_sha256(report),
            summary={"issues": len(report.issues)},
        )
        return report

    def inspect_actions(
        self,
        repository_full_name: str,
    ) -> ActionsInspection:
        api = self._connector.read_only_api()
        account = api.authenticated_user()
        report = self._actions.inspect(api, repository_full_name)
        self._record(
            ReadOnlyOperation.ACTIONS_INSPECTION,
            account_login=account.login,
            repository_full_name=repository_full_name,
            request={"repository": repository_full_name},
            evidence_sha256=self._model_sha256(report),
            summary={
                "workflows": len(report.workflows),
                "runs": len(report.runs),
                "failing_runs": list(report.failing_run_ids),
                "in_progress_runs": list(report.in_progress_run_ids),
            },
        )
        return report

    def get_receipt(self, receipt_id: UUID) -> ReadOnlyReceipt:
        return self._receipts.get(receipt_id)

    def list_receipts(self, *, limit: int = 100) -> tuple[ReadOnlyReceipt, ...]:
        return self._receipts.list_recent(limit=limit)

    def _record(
        self,
        operation: ReadOnlyOperation,
        *,
        account_login: str,
        request: dict[str, object],
        evidence_sha256: str,
        summary: dict[str, object],
        repository_full_name: str | None = None,
        requested_ref: str | None = None,
        resolved_commit_sha: str | None = None,
    ) -> ReadOnlyReceipt:
        receipt = ReadOnlyReceipt(
            operation=operation,
            account_login=account_login,
            repository_full_name=repository_full_name,
            requested_ref=requested_ref,
            resolved_commit_sha=resolved_commit_sha,
            request_sha256=self._json_sha256(request),
            evidence_sha256=evidence_sha256,
            status="verified_read_only",
            summary=summary,
        )
        self._receipts.put(receipt)
        return receipt

    @staticmethod
    def _json_sha256(value: object) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _model_sha256(cls, model) -> str:
        return cls._json_sha256(model.model_dump(mode="json"))

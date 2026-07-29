"""Loopback-only, authenticated API routes for the read-only workspace plane."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, status

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.account_intelligence import GitHubAccountIntelligenceReport
from nexuss.connectors.github.actions_monitor import ActionsInspection
from nexuss.connectors.github.build_runner import BuildExecutionDenied
from nexuss.connectors.github.operation_models import (
    BuildPlan,
    BuildRunReceipt,
    ReadOnlyReceipt,
    RepositorySelection,
    RepositorySnapshot,
    SnapshotFileContent,
    SourceAnalysisReport,
)
from nexuss.connectors.github.pull_request_manager import (
    IssueInspection,
    PullRequestInspection,
)
from nexuss.connectors.github.repository_reader import RepositoryReadReport
from nexuss.connectors.github.repository_workspace import RepositoryWorkspaceError
from nexuss.connectors.github.workspace_control import GitHubWorkspaceControlPlane


def register_github_workspace_routes(
    app: FastAPI,
    require_local_control: Callable[[Request], None],
    *,
    control_plane: GitHubWorkspaceControlPlane | None = None,
) -> None:
    plane = control_plane or GitHubWorkspaceControlPlane.from_environment()

    def authorize(request: Request, authenticated: bool) -> None:
        require_local_control(request)
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SESSION_NOT_AUTHENTICATED",
            )

    def translate(exc: Exception) -> HTTPException:
        if isinstance(exc, ConnectorError):
            code = exc.code
            http_status = (
                status.HTTP_404_NOT_FOUND
                if code == "GITHUB_RESOURCE_NOT_FOUND"
                else status.HTTP_409_CONFLICT
            )
            return HTTPException(
                status_code=http_status,
                detail={"code": code, "message": exc.message},
            )
        if isinstance(exc, RepositoryWorkspaceError):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            )
        if isinstance(exc, BuildExecutionDenied):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "GITHUB_BUILD_EXECUTION_DISABLED", "message": str(exc)},
            )
        if isinstance(exc, FileNotFoundError):
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GITHUB_WORKSPACE_RESOURCE_NOT_FOUND",
            )
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GITHUB_WORKSPACE_OPERATION_FAILED",
        )

    @app.get(
        "/v1/github-workspace/account",
        response_model=GitHubAccountIntelligenceReport,
    )
    def github_workspace_account(
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> GitHubAccountIntelligenceReport:
        authorize(request, authenticated)
        try:
            return plane.inspect_account()
        except Exception as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/github-workspace/repository/inspect",
        response_model=RepositoryReadReport,
    )
    def github_workspace_repository_inspect(
        selection: RepositorySelection,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> RepositoryReadReport:
        authorize(request, authenticated)
        try:
            return plane.inspect_repository(selection)
        except Exception as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/github-workspace/repository/snapshot",
        response_model=RepositorySnapshot,
    )
    def github_workspace_repository_snapshot(
        selection: RepositorySelection,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> RepositorySnapshot:
        authorize(request, authenticated)
        try:
            return plane.create_snapshot(selection)
        except Exception as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/github-workspace/snapshots/{snapshot_id}/files",
        response_model=SnapshotFileContent,
    )
    def github_workspace_read_file(
        snapshot_id: UUID,
        request: Request,
        path: str = Query(min_length=1, max_length=1_000),
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> SnapshotFileContent:
        authorize(request, authenticated)
        try:
            return plane.read_snapshot_file(snapshot_id, path)
        except Exception as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/github-workspace/snapshots/{snapshot_id}/analyze",
        response_model=SourceAnalysisReport,
    )
    def github_workspace_analyze(
        snapshot_id: UUID,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> SourceAnalysisReport:
        authorize(request, authenticated)
        try:
            return plane.analyze_snapshot(snapshot_id)
        except Exception as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/github-workspace/snapshots/{snapshot_id}/build-plan",
        response_model=BuildPlan,
    )
    def github_workspace_build_plan(
        snapshot_id: UUID,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> BuildPlan:
        authorize(request, authenticated)
        try:
            return plane.create_build_plan(snapshot_id)
        except Exception as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/github-workspace/snapshots/{snapshot_id}/build",
        response_model=BuildRunReceipt,
    )
    def github_workspace_build(
        snapshot_id: UUID,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> BuildRunReceipt:
        authorize(request, authenticated)
        try:
            return plane.execute_build(snapshot_id)
        except Exception as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/github-workspace/repositories/{owner}/{repository}/pull-requests",
        response_model=PullRequestInspection,
    )
    def github_workspace_pull_requests(
        owner: str,
        repository: str,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
        state_filter: str = Query(default="open", alias="state", pattern="^(open|closed|all)$"),
    ) -> PullRequestInspection:
        authorize(request, authenticated)
        try:
            return plane.inspect_pull_requests(
                f"{owner}/{repository}",
                state=state_filter,
            )
        except Exception as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/github-workspace/repositories/{owner}/{repository}/issues",
        response_model=IssueInspection,
    )
    def github_workspace_issues(
        owner: str,
        repository: str,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
        state_filter: str = Query(default="open", alias="state", pattern="^(open|closed|all)$"),
    ) -> IssueInspection:
        authorize(request, authenticated)
        try:
            return plane.inspect_issues(
                f"{owner}/{repository}",
                state=state_filter,
            )
        except Exception as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/github-workspace/repositories/{owner}/{repository}/actions",
        response_model=ActionsInspection,
    )
    def github_workspace_actions(
        owner: str,
        repository: str,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> ActionsInspection:
        authorize(request, authenticated)
        try:
            return plane.inspect_actions(f"{owner}/{repository}")
        except Exception as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/github-workspace/receipts",
        response_model=list[ReadOnlyReceipt],
    )
    def github_workspace_receipts(
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[ReadOnlyReceipt]:
        authorize(request, authenticated)
        return list(plane.list_receipts(limit=limit))

    @app.get(
        "/v1/github-workspace/receipts/{receipt_id}",
        response_model=ReadOnlyReceipt,
    )
    def github_workspace_receipt(
        receipt_id: UUID,
        request: Request,
        authenticated: bool = Header(alias="X-Nexuss-Session-Authenticated"),
    ) -> ReadOnlyReceipt:
        authorize(request, authenticated)
        try:
            return plane.get_receipt(receipt_id)
        except Exception as exc:
            raise translate(exc) from exc

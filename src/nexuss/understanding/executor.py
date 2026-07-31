"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.


Read-only GitHub execution adapter for resolved P6.6B goals.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID

from nexuss.understanding.models import (
    GoalExecutionResult,
    GoalInterpretation,
    GoalKind,
)
from nexuss.understanding.normalization import normalize_requested_ref


class GitHubReadOnlyPlane(Protocol):
    def inspect_account(self): ...
    def inspect_repository(self, selection): ...
    def create_snapshot(self, selection): ...
    def analyze_snapshot(self, snapshot_id: UUID): ...
    def create_build_plan(self, snapshot_id: UUID): ...
    def inspect_pull_requests(self, repository_full_name: str, *, state: str = "open"): ...
    def inspect_issues(self, repository_full_name: str, *, state: str = "open"): ...
    def inspect_actions(self, repository_full_name: str): ...
    def list_receipts(self, *, limit: int = 100): ...


class GitHubGoalExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _dump(value) -> dict[str, object]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, dict):
        return value
    raise TypeError(f"Unsupported execution result: {type(value).__name__}")


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _receipt_ids(plane: GitHubReadOnlyPlane, before: set[UUID]) -> tuple[UUID, ...]:
    try:
        receipts = tuple(plane.list_receipts(limit=100))
    except Exception:  # noqa: BLE001 - receipt discovery is best-effort
        return ()
    result: list[UUID] = []
    for receipt in receipts:
        receipt_id = getattr(receipt, "receipt_id", None)
        if isinstance(receipt_id, UUID) and receipt_id not in before:
            result.append(receipt_id)
    return tuple(result)


class GitHubReadOnlyGoalExecutor:
    def __init__(self, plane: GitHubReadOnlyPlane) -> None:
        self._plane = plane

    def execute(self, interpretation: GoalInterpretation) -> GoalExecutionResult:
        before = self._current_receipts()
        goal = interpretation.goal

        if goal is GoalKind.GITHUB_CAPABILITIES:
            data = {
                "read_only": [
                    "verify connected account",
                    "list authorized repositories",
                    "inspect repository metadata and commits",
                    "create immutable snapshots",
                    "analyze source architecture",
                    "prepare build and test plans",
                    "inspect pull requests, issues, and GitHub Actions",
                ],
                "approval_bound": [
                    "create a private repository from an approved ZIP",
                    "publish an approved ZIP manifest to an empty repository",
                ],
                "not_enabled": [
                    "direct default-branch writes",
                    "repository modification through the read-only workspace",
                    "branch pushing and pull-request creation",
                    "merging, deletion, deployment, and webhook monitoring",
                ],
            }
            message = (
                "Current GitHub capability boundary:\n"
                "Read-only, no phone approval: account and repository inventory; "
                "metadata and commit inspection; immutable snapshots; source "
                "analysis; build-plan generation; pull-request, issue, and "
                "GitHub Actions inspection.\n"
                "Phone-approved writes already available: the bounded private "
                "repository and verified ZIP publication workflow.\n"
                "Not enabled in P6.6B: direct main writes, general repository "
                "modification, branch pushes, pull-request creation, merging, "
                "deletion, deployment, and webhooks. No action was performed."
            )
            return GoalExecutionResult(
                operation="github_capabilities",
                assistant_message=message,
                data=data,
                evidence_sha256=_sha256(data),
            )

        if goal is GoalKind.GITHUB_ACCOUNT_IDENTITY:
            report = self._plane.inspect_account()
            data = _dump(report)
            account = data.get("account", {})
            login = account.get("login", "unknown") if isinstance(account, dict) else "unknown"
            message = (
                f"GitHub connector status: connected as {login}. "
                "This was a read-only identity verification. No GitHub write was performed."
            )
            return self._result("github_account_identity", message, data, before)

        if goal is GoalKind.GITHUB_REPOSITORY_INVENTORY:
            report = self._plane.inspect_account()
            data = _dump(report)
            inventory = data.get("repository_inventory", {})
            repositories = inventory.get("repositories", []) if isinstance(inventory, dict) else []
            lines = []
            for item in repositories:
                if not isinstance(item, dict):
                    continue
                visibility = "private" if item.get("private") else "public"
                flags = [
                    name
                    for name in ("archived", "disabled", "fork")
                    if item.get(name)
                ]
                suffix = f"; {', '.join(flags)}" if flags else ""
                lines.append(f"- {item.get('full_name', 'unknown')} — {visibility}{suffix}")
            summary = "\n".join(lines) if lines else "No authorized repositories were returned."
            message = (
                "Authorized GitHub repositories:\n"
                f"{summary}\n\nNo GitHub write was performed."
            )
            return self._result("github_repository_inventory", message, data, before)

        repository_full_name = interpretation.entities.repository_full_name
        if not repository_full_name:
            raise GitHubGoalExecutionError(
                "GITHUB_REPOSITORY_REQUIRED",
                "A specific GitHub repository is required.",
            )
        explicit_ref = normalize_requested_ref(interpretation.entities.ref)
        requested_ref = explicit_ref or self._default_branch(repository_full_name)
        selection = self._selection(repository_full_name, requested_ref)

        if goal in {
            GoalKind.GITHUB_REPOSITORY_INSPECT,
            GoalKind.GITHUB_COMMITS_LIST,
        }:
            report = self._plane.inspect_repository(selection)
            data = _dump(report)
            if goal is GoalKind.GITHUB_COMMITS_LIST:
                commits = data.get("recent_commits", [])
                lines = []
                for item in commits[:12] if isinstance(commits, list) else []:
                    if not isinstance(item, dict):
                        continue
                    sha = str(item.get("sha", ""))[:8]
                    message_text = str(item.get("message", "")).splitlines()[0]
                    author = item.get("author_login") or item.get("author_name") or "unknown"
                    lines.append(f"- {sha} {message_text} — {author}")
                message = (
                    f"Recent commits for {repository_full_name} at {requested_ref}:\n"
                    + ("\n".join(lines) if lines else "No commits were returned.")
                    + "\n\nNo GitHub write was performed."
                )
                return self._result("github_commits_list", message, data, before)

            repository = data.get("repository", {})
            resolved = data.get("resolved_commit", {})
            default_branch = (
                repository.get("default_branch", "unknown")
                if isinstance(repository, dict)
                else "unknown"
            )
            commit_sha = (
                resolved.get("sha", "unknown")
                if isinstance(resolved, dict)
                else "unknown"
            )
            message = (
                f"Verified {repository_full_name}. Default branch: {default_branch}. "
                f"Resolved {requested_ref} to commit {commit_sha}. "
                "The operation was read-only and repository code was not executed."
            )
            return self._result("github_repository_inspect", message, data, before)

        if goal in {
            GoalKind.GITHUB_REPOSITORY_ANALYZE,
            GoalKind.GITHUB_IMPORTANT_FILES,
            GoalKind.GITHUB_BUILD_PLAN,
        }:
            snapshot = self._plane.create_snapshot(selection)
            snapshot_data = _dump(snapshot)
            snapshot_id = UUID(str(snapshot_data["snapshot_id"]))
            analysis = self._plane.analyze_snapshot(snapshot_id)
            analysis_data = _dump(analysis)

            if goal is GoalKind.GITHUB_BUILD_PLAN:
                plan = self._plane.create_build_plan(snapshot_id)
                plan_data = _dump(plan)
                commands = []
                for item in plan_data.get("commands", []):
                    if not isinstance(item, dict):
                        continue
                    argv = " ".join(str(part) for part in item.get("argv", []))
                    commands.append(
                        f"- {item.get('label', 'command')}: {argv} "
                        f"({item.get('reason', 'no reason supplied')})"
                    )
                message = (
                    f"Prepared a build and test plan for {repository_full_name} "
                    f"at commit {snapshot_data.get('resolved_commit_sha')}.\n"
                    + ("\n".join(commands) if commands else "No build commands were detected.")
                    + f"\n\nExecution allowed: {plan_data.get('execution_allowed', False)}. "
                    "No repository-controlled command was executed."
                )
                payload = {
                    "snapshot": snapshot_data,
                    "analysis": analysis_data,
                    "build_plan": plan_data,
                }
                return self._result("github_build_plan", message, payload, before)

            languages = ", ".join(
                str(item.get("language"))
                for item in analysis_data.get("languages", [])
                if isinstance(item, dict)
            ) or "not detected"
            build_systems = ", ".join(
                str(item) for item in analysis_data.get("build_systems", [])
            ) or "not detected"
            entry_points = analysis_data.get("likely_entry_points", [])
            tests = analysis_data.get("test_targets", [])
            dependencies = analysis_data.get("dependency_manifests", [])

            if goal is GoalKind.GITHUB_IMPORTANT_FILES:
                candidates: list[str] = []
                for item in entry_points:
                    candidates.append(str(item))
                for item in tests:
                    candidates.append(str(item))
                for item in dependencies:
                    if isinstance(item, dict):
                        candidates.append(str(item.get("path", "")))
                deduplicated = []
                seen = set()
                for item in candidates:
                    if item and item not in seen:
                        seen.add(item)
                        deduplicated.append(item)
                lines = [f"- {item}" for item in deduplicated[:20]]
                message = (
                    f"Important files detected in {repository_full_name}:\n"
                    + ("\n".join(lines) if lines else "No high-confidence files were detected.")
                    + (
                        "\n\nThe list is derived from the immutable snapshot "
                        "and no file was modified."
                    )
                )
                payload = {"snapshot": snapshot_data, "analysis": analysis_data}
                return self._result("github_important_files", message, payload, before)

            message = (
                f"Analyzed {repository_full_name} at commit "
                f"{snapshot_data.get('resolved_commit_sha')}. "
                f"Languages: {languages}. Build systems: {build_systems}. "
                f"Source files: {analysis_data.get('source_files', 0)}; "
                f"test files: {analysis_data.get('test_files', 0)}. "
                "No file was modified and repository code was not executed."
            )
            payload = {"snapshot": snapshot_data, "analysis": analysis_data}
            return self._result("github_repository_analyze", message, payload, before)

        if goal is GoalKind.GITHUB_PULL_REQUESTS_LIST:
            report = self._plane.inspect_pull_requests(repository_full_name, state="open")
            data = _dump(report)
            pulls = data.get("pull_requests", [])
            lines = []
            for item in pulls if isinstance(pulls, list) else []:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- #{item.get('number')} {item.get('title')} — "
                    f"{item.get('author_login') or 'unknown'}; "
                    f"{item.get('head_ref')} → {item.get('base_ref')}; "
                    f"{'draft' if item.get('draft') else 'ready'}"
                )
            message = (
                f"Open pull requests for {repository_full_name}:\n"
                + ("\n".join(lines) if lines else "No open pull requests.")
                + "\n\nNo review, comment, or GitHub write was submitted."
            )
            return self._result("github_pull_requests_list", message, data, before)

        if goal is GoalKind.GITHUB_ISSUES_LIST:
            report = self._plane.inspect_issues(repository_full_name, state="open")
            data = _dump(report)
            issues = data.get("issues", [])
            lines = []
            for item in issues if isinstance(issues, list) else []:
                if not isinstance(item, dict):
                    continue
                labels = ", ".join(str(value) for value in item.get("labels", [])) or "no labels"
                assignees = (
                    ", ".join(
                        str(value)
                        for value in item.get("assignees", [])
                    )
                    or "unassigned"
                )
                lines.append(
                    f"- #{item.get('number')} {item.get('title')} — "
                    f"{labels}; {assignees}"
                )
            message = (
                f"Open issues for {repository_full_name}:\n"
                + ("\n".join(lines) if lines else "No open issues.")
                + "\n\nNo issue was edited."
            )
            return self._result("github_issues_list", message, data, before)

        if goal is GoalKind.GITHUB_ACTIONS_INSPECT:
            report = self._plane.inspect_actions(repository_full_name)
            data = _dump(report)
            runs = data.get("runs", [])
            lines = []
            for item in runs[:15] if isinstance(runs, list) else []:
                if not isinstance(item, dict):
                    continue
                result = item.get("conclusion") or item.get("status") or "unknown"
                lines.append(
                    f"- {item.get('name', 'workflow')} on "
                    f"{item.get('branch') or 'unknown branch'} — {result}"
                )
            message = (
                f"Latest GitHub Actions runs for {repository_full_name}:\n"
                + ("\n".join(lines) if lines else "No workflow runs were returned.")
                + "\n\nNo workflow was rerun or modified."
            )
            return self._result("github_actions_inspect", message, data, before)

        raise GitHubGoalExecutionError(
            "GITHUB_GOAL_NOT_READ_ONLY",
            "This goal is not executable in the P6.6B read-only boundary.",
        )

    def repositories(self) -> tuple[dict[str, object], ...]:
        report = self._plane.inspect_account()
        data = _dump(report)
        inventory = data.get("repository_inventory", {})
        repositories = (
            inventory.get("repositories", [])
            if isinstance(inventory, dict)
            else []
        )
        return tuple(
            item for item in repositories if isinstance(item, dict)
        )

    def _default_branch(self, repository_full_name: str) -> str:
        for repository in self.repositories():
            if str(repository.get("full_name", "")).casefold() == repository_full_name.casefold():
                return str(repository.get("default_branch") or "main")
        return "main"

    @staticmethod
    def _selection(repository_full_name: str, requested_ref: str):
        try:
            from nexuss.connectors.github.operation_models import RepositorySelection
        except ImportError as exc:
            raise GitHubGoalExecutionError(
                "GITHUB_WORKSPACE_NOT_INSTALLED",
                "The P6.6A GitHub workspace contracts are unavailable.",
            ) from exc
        return RepositorySelection(
            repository_full_name=repository_full_name,
            requested_ref=requested_ref,
        )

    def _current_receipts(self) -> set[UUID]:
        try:
            return {
                receipt.receipt_id
                for receipt in self._plane.list_receipts(limit=100)
                if isinstance(getattr(receipt, "receipt_id", None), UUID)
            }
        except Exception:  # noqa: BLE001 - receipt discovery is best-effort
            return set()

    def _result(
        self,
        operation: str,
        message: str,
        data: dict[str, object],
        before: set[UUID],
    ) -> GoalExecutionResult:
        return GoalExecutionResult(
            operation=operation,
            assistant_message=message,
            data=data,
            receipt_ids=_receipt_ids(self._plane, before),
            evidence_sha256=_sha256(data),
        )

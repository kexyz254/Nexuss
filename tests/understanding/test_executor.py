"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Read-only GitHub result formatting and receipt tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.executor import GitHubReadOnlyGoalExecutor


class Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, *, mode="python"):
        assert mode == "json"
        return self.payload


class FakeReceipt:
    def __init__(self):
        self.receipt_id = uuid4()


class FakePlane:
    def __init__(self):
        self.receipts = []
        self.calls = []

    def _record(self, name):
        self.calls.append(name)
        receipt = FakeReceipt()
        self.receipts.append(receipt)
        return receipt

    def list_receipts(self, *, limit=100):
        return tuple(reversed(self.receipts[-limit:]))

    def inspect_account(self):
        self._record("account")
        return Dumpable(
            {
                "account": {"login": "kexyz254"},
                "repository_inventory": {
                    "repositories": [
                        {
                            "full_name": "kexyz254/GlyphSentry-Core-Final",
                            "private": True,
                            "archived": False,
                            "disabled": False,
                            "fork": False,
                            "default_branch": "main",
                        }
                    ]
                },
            }
        )

    def inspect_repository(self, selection):
        self._record("inspect")
        return Dumpable(
            {
                "repository": {"default_branch": "main"},
                "resolved_commit": {"sha": "a" * 40},
                "recent_commits": [
                    {
                        "sha": "b" * 40,
                        "message": "Fix parser boundary",
                        "author_login": "kexyz254",
                    }
                ],
            }
        )

    def create_snapshot(self, selection):
        self._record("snapshot")
        return Dumpable(
            {
                "snapshot_id": str(uuid4()),
                "resolved_commit_sha": "c" * 40,
            }
        )

    def analyze_snapshot(self, snapshot_id):
        self._record("analyze")
        return Dumpable(
            {
                "languages": [{"language": "Python"}],
                "build_systems": ["pyproject"],
                "likely_entry_points": ["src/main.py"],
                "test_targets": ["tests/test_main.py"],
                "dependency_manifests": [
                    {"path": "pyproject.toml"}
                ],
                "source_files": 10,
                "test_files": 3,
            }
        )

    def create_build_plan(self, snapshot_id):
        self._record("build-plan")
        return Dumpable(
            {
                "commands": [
                    {
                        "label": "Tests",
                        "argv": ["python", "-m", "pytest", "-q"],
                        "reason": "Run tests",
                    }
                ],
                "execution_allowed": False,
            }
        )

    def inspect_pull_requests(self, repository_full_name, *, state="open"):
        self._record("pulls")
        return Dumpable(
            {
                "pull_requests": [
                    {
                        "number": 7,
                        "title": "Improve parser",
                        "author_login": "dev",
                        "head_ref": "feature/parser",
                        "base_ref": "main",
                        "draft": False,
                    }
                ]
            }
        )

    def inspect_issues(self, repository_full_name, *, state="open"):
        self._record("issues")
        return Dumpable({"issues": []})

    def inspect_actions(self, repository_full_name):
        self._record("actions")
        return Dumpable(
            {
                "runs": [
                    {
                        "name": "CI",
                        "branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        )


@pytest.fixture
def executor(monkeypatch):
    plane = FakePlane()
    result = GitHubReadOnlyGoalExecutor(plane)
    monkeypatch.setattr(
        result,
        "_selection",
        lambda repository_full_name, requested_ref: SimpleNamespace(
            repository_full_name=repository_full_name,
            requested_ref=requested_ref,
        ),
    )
    return result, plane


def test_account_identity_is_read_only(executor) -> None:
    runner, plane = executor
    interpretation = GoalClassifier().classify(
        "Identify my connected GitHub account."
    )

    result = runner.execute(interpretation)

    assert "kexyz254" in result.assistant_message
    assert result.github_write_performed is False
    assert result.credentials_exposed is False
    assert len(result.receipt_ids) == 1
    assert plane.calls == ["account"]


def test_repository_analysis_creates_snapshot_and_analysis(executor) -> None:
    runner, plane = executor
    interpretation = GoalClassifier().classify(
        "Analyze kexyz254/GlyphSentry-Core-Final."
    )

    result = runner.execute(interpretation)

    assert "Python" in result.assistant_message
    assert plane.calls == ["account", "snapshot", "analyze"]
    assert len(result.receipt_ids) == 3


def test_build_plan_never_executes_build(executor) -> None:
    runner, plane = executor
    interpretation = GoalClassifier().classify(
        "Prepare a build plan for kexyz254/GlyphSentry-Core-Final. Plan only."
    )

    result = runner.execute(interpretation)

    assert "Execution allowed: False" in result.assistant_message
    assert "build-plan" in plane.calls
    assert "build" not in plane.calls

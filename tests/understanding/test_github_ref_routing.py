"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

P6.6B.1 GitHub ref-routing regression tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.executor import GitHubReadOnlyGoalExecutor
from nexuss.understanding.normalization import normalize_requested_ref


class _Dumpable:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        assert mode == "json"
        return self._payload


class _Receipt:
    def __init__(self) -> None:
        self.receipt_id = uuid4()


class _Plane:
    def __init__(self) -> None:
        self.selections: list[object] = []
        self.receipts: list[_Receipt] = []

    def list_receipts(self, *, limit: int = 100):
        return tuple(reversed(self.receipts[-limit:]))

    def inspect_account(self):
        receipt = _Receipt()
        self.receipts.append(receipt)
        return _Dumpable(
            {
                "account": {"login": "kexyz254"},
                "repository_inventory": {
                    "repositories": [
                        {
                            "full_name": "kexyz254/GlyphSentry-Core-Final",
                            "default_branch": "main",
                        }
                    ]
                },
            }
        )

    def inspect_repository(self, selection):
        self.selections.append(selection)
        receipt = _Receipt()
        self.receipts.append(receipt)
        return _Dumpable(
            {
                "repository": {"default_branch": "main"},
                "resolved_commit": {"sha": "f" * 40},
                "recent_commits": [],
            }
        )

    def create_snapshot(self, selection):
        raise AssertionError("Snapshot was not expected.")

    def analyze_snapshot(self, snapshot_id):
        raise AssertionError("Analysis was not expected.")

    def create_build_plan(self, snapshot_id):
        raise AssertionError("Build plan was not expected.")

    def inspect_pull_requests(self, repository_full_name, *, state="open"):
        raise AssertionError("Pull-request inspection was not expected.")

    def inspect_issues(self, repository_full_name, *, state="open"):
        raise AssertionError("Issue inspection was not expected.")

    def inspect_actions(self, repository_full_name):
        raise AssertionError("Actions inspection was not expected.")


@pytest.mark.parametrize(
    "utterance",
    [
        (
            "Inspect kexyz254/GlyphSentry-Core-Final. Verify the default "
            "branch and exact current commit. Do not modify or execute code."
        ),
        "Inspect kexyz254/GlyphSentry-Core-Final at the default branch.",
        "Show the current commit for kexyz254/GlyphSentry-Core-Final.",
    ],
)
def test_descriptive_branch_language_does_not_become_a_ref(
    utterance: str,
) -> None:
    interpretation = GoalClassifier().classify(utterance)

    assert interpretation.entities.ref is None


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        (
            "Inspect kexyz254/GlyphSentry-Core-Final branch release/2.0.",
            "release/2.0",
        ),
        (
            "Inspect kexyz254/GlyphSentry-Core-Final tag v2.1.0.",
            "v2.1.0",
        ),
        (
            "Inspect kexyz254/GlyphSentry-Core-Final commit sha abc123def.",
            "abc123def",
        ),
    ],
)
def test_explicit_refs_are_preserved(
    utterance: str,
    expected: str,
) -> None:
    interpretation = GoalClassifier().classify(utterance)

    assert interpretation.entities.ref == expected


@pytest.mark.parametrize(
    "candidate",
    ["and", "default", "current", "exact", "sha", "hash", "the"],
)
def test_reserved_natural_language_tokens_are_not_refs(
    candidate: str,
) -> None:
    assert normalize_requested_ref(candidate) is None


def test_executor_defensively_rejects_false_ref_and_uses_default_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plane = _Plane()
    executor = GitHubReadOnlyGoalExecutor(plane)

    monkeypatch.setattr(
        executor,
        "_selection",
        lambda repository_full_name, requested_ref: SimpleNamespace(
            repository_full_name=repository_full_name,
            requested_ref=requested_ref,
        ),
    )

    interpretation = GoalClassifier().classify(
        "Inspect kexyz254/GlyphSentry-Core-Final."
    )
    interpretation = interpretation.model_copy(
        update={
            "entities": interpretation.entities.model_copy(
                update={"ref": "and"}
            )
        }
    )

    result = executor.execute(interpretation)

    assert len(plane.selections) == 1
    assert plane.selections[0].requested_ref == "main"
    assert "Resolved main to commit" in result.assistant_message
    assert result.github_write_performed is False

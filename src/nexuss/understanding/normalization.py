"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Text normalization, entity extraction, and explicit constraint parsing.
"""

from __future__ import annotations

import re

from nexuss.understanding.models import GoalConstraints, GoalEntities

_REPOSITORY_FULL_NAME = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:https?://github\.com/)?"
    r"(?P<owner>[A-Za-z0-9_.-]{1,100})/"
    r"(?P<repository>[A-Za-z0-9_.-]{1,100})"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
_REPOSITORY_NAME = re.compile(
    r"\b(?:repository|repo)\s+(?:named|called|is)?\s*"
    r"""[`'"]?(?P<repository>[A-Za-z0-9_.-]{1,100})[`'"]?""",
    re.IGNORECASE,
)
_REF_PATTERN = re.compile(
    r"""\b(?:branch|ref|tag|commit(?:\s+(?:sha|hash))?)\s+[`'"]?"""
    r"""(?P<ref>[A-Za-z0-9._/-]{1,255})[`'"]?""",
    re.IGNORECASE,
)
_INVALID_REF_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "branch",
        "called",
        "commit",
        "current",
        "default",
        "do",
        "exact",
        "for",
        "from",
        "hash",
        "latest",
        "name",
        "named",
        "not",
        "on",
        "or",
        "recent",
        "ref",
        "sha",
        "tag",
        "the",
        "this",
        "to",
        "with",
        "without",
    }
)
_ISSUE_PATTERN = re.compile(
    r"\b(?:issue|bug)\s*#?\s*(?P<number>[1-9][0-9]*)\b",
    re.IGNORECASE,
)
_PR_PATTERN = re.compile(
    r"\b(?:pull request|pr)\s*#?\s*(?P<number>[1-9][0-9]*)\b",
    re.IGNORECASE,
)
_FILE_PATTERN = re.compile(
    r"""\b(?:file|path)\s+[`'"](?P<path>[^`'"]{1,1000})[`'"]""",
    re.IGNORECASE,
)

_NEGATE_MODIFICATION = (
    "do not modify",
    "don't modify",
    "do not change",
    "don't change",
    "do not edit",
    "don't edit",
    "read only",
    "read-only",
    "without modifying",
    "no changes",
)
_NEGATE_EXECUTION = (
    "do not execute",
    "don't execute",
    "do not run",
    "don't run",
    "without running",
    "plan only",
)
_NEGATE_EXTERNAL_WRITE = (
    "do not push",
    "don't push",
    "do not publish",
    "don't publish",
    "do not open a pull request",
    "don't open a pull request",
    "local only",
)
_NEGATE_NETWORK = (
    "do not contact external services",
    "don't contact external services",
    "do not access github",
    "don't access github",
    "do not use the internet",
    "don't use the internet",
    "without internet",
    "no network",
    "offline only",
)
_APPROVAL_REQUIRED = (
    "after i approve",
    "after my approval",
    "require approval",
    "phone approval",
    "paired phone",
    "biometric approval",
)
_APPROVAL_BYPASS = (
    "ignore the phone approval",
    "skip approval",
    "bypass approval",
    "without approval",
    "use the stored github credentials",
    "use stored github credentials",
)
_DIRECT_MAIN = (
    "directly to main",
    "push to main",
    "push directly to main",
    "write directly to main",
)
_FORCE_PUSH = (
    "force push",
    "force-push",
    "--force",
)


def normalize_utterance(value: str) -> str:
    return " ".join(value.strip().split())


def folded(value: str) -> str:
    return normalize_utterance(value).casefold()


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def normalize_requested_ref(value: str | None) -> str | None:
    """Return a defensible explicit Git ref or ``None``.

    Natural-language conjunctions and descriptive words must never become
    branch, tag, or commit references. GitHub's default branch is resolved by
    the read-only workspace when the user did not provide a valid explicit ref.
    """

    if value is None:
        return None

    candidate = value.strip().strip("`'\"").rstrip(".,;:!?)]}")

    if not candidate:
        return None

    if candidate.casefold() in _INVALID_REF_TOKENS:
        return None

    return candidate


def extract_entities(utterance: str) -> GoalEntities:
    text = normalize_utterance(utterance)
    full = _REPOSITORY_FULL_NAME.search(text)
    owner = None
    repository = None
    repository_full_name = None

    if full:
        owner = full.group("owner")
        repository = full.group("repository").rstrip(".,;:!?)]}").removesuffix(".git")
        repository_full_name = f"{owner}/{repository}"
    else:
        repository_match = _REPOSITORY_NAME.search(text)
        if repository_match:
            repository = (
                repository_match.group("repository")
                .rstrip(".,;:!?)]}")
                .removesuffix(".git")
            )

    requested_ref = None
    for ref_match in _REF_PATTERN.finditer(text):
        requested_ref = normalize_requested_ref(ref_match.group("ref"))
        if requested_ref is not None:
            break

    issue_match = _ISSUE_PATTERN.search(text)
    pr_match = _PR_PATTERN.search(text)
    file_match = _FILE_PATTERN.search(text)

    return GoalEntities(
        owner=owner,
        repository=repository,
        repository_full_name=repository_full_name,
        ref=requested_ref,
        issue_number=int(issue_match.group("number")) if issue_match else None,
        pull_request_number=int(pr_match.group("number")) if pr_match else None,
        file_path=file_match.group("path").strip() if file_match else None,
    )


def extract_constraints(utterance: str) -> GoalConstraints:
    text = folded(utterance)
    read_only = (
        contains_any(text, _NEGATE_MODIFICATION)
        or re.search(
            r"\b(?:do not|don't|never)\b[^.]{0,100}\b(?:modify|change|edit)\b",
            text,
        )
        is not None
    )
    plan_only = "plan only" in text or "prepare a plan" in text
    no_execution = (
        contains_any(text, _NEGATE_EXECUTION)
        or re.search(
            r"\b(?:do not|don't|never)\b[^.]{0,100}\b(?:execute|run)\b",
            text,
        )
        is not None
    )
    no_external_write = (
        contains_any(text, _NEGATE_EXTERNAL_WRITE)
        or re.search(
            r"\b(?:do not|don't|never)\b[^.]{0,120}\b(?:push|publish)\b",
            text,
        )
        is not None
    )
    no_network = contains_any(text, _NEGATE_NETWORK)
    approval_required = contains_any(text, _APPROVAL_REQUIRED)
    bypass = contains_any(text, _APPROVAL_BYPASS)
    direct_main = contains_any(text, _DIRECT_MAIN)
    force_push = contains_any(text, _FORCE_PUSH)

    return GoalConstraints(
        read_only=read_only,
        plan_only=plan_only,
        allow_modification=not read_only,
        allow_code_execution=not no_execution,
        allow_external_writes=not no_external_write,
        allow_network_access=not no_network,
        require_tests_pass=(
            "after tests pass" in text
            or "if tests pass" in text
            or "only if tests pass" in text
        ),
        require_phone_approval=True if approval_required else None,
        direct_default_branch_write_requested=direct_main,
        approval_bypass_requested=bypass,
        force_push_requested=force_push,
    )

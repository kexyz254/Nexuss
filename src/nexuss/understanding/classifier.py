"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Deterministic, precedence-based intent classification for the P6.6B gateway.
"""

from __future__ import annotations

from dataclasses import dataclass

from nexuss.understanding.models import (
    GoalConstraints,
    GoalInterpretation,
    GoalKind,
    IntentDomain,
    OperationKind,
)
from nexuss.understanding.normalization import (
    contains_any,
    extract_constraints,
    extract_entities,
    folded,
    normalize_utterance,
)

_GITHUB_TERMS = (
    "github",
    "repository",
    "repositories",
    "repo",
    "pull request",
    " pr ",
    "issue",
    "actions",
    "workflow",
    "commit",
    "branch",
)
_GITHUB_CAPABILITIES = (
    "what you can currently do with my connected github account",
    "what can you do with my github account",
    "github capabilities",
    "github operations available",
    "read-only capabilities",
    "read only capabilities",
)
_ACCOUNT_IDENTITY = (
    "connected github account",
    "github account connected",
    "identify the github account",
    "which github account",
    "who am i connected as",
    "github connector status",
)
_REPOSITORY_INVENTORY = (
    "list the repositories",
    "list repositories",
    "list my repositories",
    "show repositories",
    "show my repositories",
    "show my repos",
    "available repositories",
    "repositories available",
    "authorized repositories",
    "authorised repositories",
    "my repositories",
    "my repos",
    "repository inventory",
)
_REPOSITORY_INSPECT = (
    "inspect",
    "verify the repository",
    "repository identity",
    "default branch",
    "current commit",
    "metadata",
)
_REPOSITORY_ANALYZE = (
    "analyze",
    "architecture",
    "major modules",
    "entry points",
    "dependency files",
    "build systems",
    "primary languages",
)
_IMPORTANT_FILES = (
    "important source files",
    "most important files",
    "key files",
    "important files",
)
_BUILD_PLAN = (
    "build and test plan",
    "build plan",
    "test plan",
    "commands you would run",
    "plan only",
)
_BUILD_EXECUTE = (
    "build the",
    "run all tests",
    "run the tests",
    "execute the build",
)
_COMMITS = (
    "recent commits",
    "commit history",
    "show commits",
    "list commits",
)
_PULL_REQUESTS = (
    "open pull requests",
    "list pull requests",
    "show pull requests",
    "review status",
)
_ISSUES = (
    "open issues",
    "list issues",
    "show issues",
)
_ACTIONS = (
    "github actions",
    "workflow runs",
    "latest workflow",
    "latest actions",
    "failing workflow",
    "ci runs",
)
_CHANGE_REQUESTS = (
    "fix ",
    "change ",
    "modify ",
    "edit ",
    "update ",
    "open a pull request",
    "open a pr",
    "push ",
    "commit ",
)
_DELETE_REQUESTS = (
    "delete repository",
    "delete the repository",
    "remove repository",
    "destroy repository",
)
_LOCAL_WORKSPACE = (
    "this workspace",
    "local workspace",
    "working tree",
    "disk space",
    "local branch",
)
_CAPABILITIES = (
    "what can you do",
    "show capabilities",
    "explain what you can do",
    "current capabilities",
)
_RESEARCH = (
    "research ",
    "look up ",
    "find information",
    "why ",
    "compare ",
    "summarise ",
    "summarize ",
    "explain ",
    "what is ",
    "who is ",
)
_MEDIA = (
    "find media",
    "find a video",
    "youtube",
    "play ",
    "music",
)
_NOTE = (
    "create a note",
    "make a note",
    "save a note",
    "write a note",
)
_MEMORY = (
    "remember ",
    "recall ",
    "forget ",
    "what did i tell you",
)
_DEVICE = (
    "launch ",
    "open on phone",
    "open web search",
    "pair phone",
    "unpair phone",
)
_ARCHIVE = (
    "attached zip",
    "this zip",
    "publish the zip",
    "deploy this zip",
    "archive import",
)
_DEPLOY = (
    "deploy ",
    "release ",
    "ship ",
)
_SYSTEM_HEALTH = (
    "system health",
    "nexuss health",
    "health status",
    "is nexuss ready",
    "is the system ready",
    "check nexuss status",
)
_SMALL_TALK = (
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "thank you",
    "thanks",
    "how are you",
)
_DATETIME = (
    "what time",
    "current time",
    "what date",
    "today's date",
    "todays date",
    "what day is it",
)
_REPOSITORY_GENERAL_READ = (
    "tell me about",
    "review the repository",
    "review repository",
    "check the repository",
    "check repository",
    "summarize the repository",
    "summarise the repository",
)
_AMBIGUOUS = (
    "fix it",
    "check it",
    "check the latest one",
    "make everything better",
    "do it",
    "handle it",
    "deploy the project",
)


@dataclass(frozen=True)
class _Decision:
    domain: IntentDomain
    goal: GoalKind
    operation: OperationKind
    confidence: float
    evidence: tuple[str, ...]
    rationale: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()


class GoalClassifier:
    """Classify natural-language goals without granting execution authority."""

    def classify(self, utterance: str) -> GoalInterpretation:
        display = normalize_utterance(utterance)
        text = folded(display)
        entities = extract_entities(display)
        constraints = extract_constraints(display)
        decision = self._decide(text, entities.repository_full_name, entities.repository)
        conflicts = self._constraint_conflicts(decision.operation, constraints)

        return GoalInterpretation(
            original_utterance=display,
            normalized_utterance=text,
            domain=decision.domain,
            goal=decision.goal,
            operation=decision.operation,
            confidence=decision.confidence,
            entities=entities,
            constraints=constraints,
            missing_fields=decision.missing_fields,
            constraint_conflicts=conflicts,
            evidence=decision.evidence,
            rationale=decision.rationale,
            grants_authority=False,
        )

    def _decide(
        self,
        text: str,
        repository_full_name: str | None,
        repository_name: str | None,
    ) -> _Decision:
        github_context = (
            contains_any(text, _GITHUB_TERMS)
            or repository_full_name is not None
            or repository_name is not None
        )

        if "approval" in text and contains_any(
            text,
            (
                "ignore",
                "skip",
                "bypass",
                "without",
                "stored github credentials",
            ),
        ):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_APPROVAL_BYPASS,
                OperationKind.WRITE,
                0.99,
                ("approval-bypass language",),
                ("Approval cannot be inferred, delegated, or bypassed.",),
            )

        if github_context and contains_any(text, _DELETE_REQUESTS):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_DELETE_REPOSITORY,
                OperationKind.DESTRUCTIVE,
                0.99,
                ("destructive repository verb",),
                ("Repository deletion is outside the P6.6B authority boundary.",),
            )

        if github_context and (
            "directly to main" in text
            or "push directly to main" in text
            or "push to main without" in text
        ):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_PUSH_DIRECT_MAIN,
                OperationKind.WRITE,
                0.99,
                ("direct default-branch write",),
                ("Direct default-branch writes are prohibited.",),
            )

        if github_context and contains_any(text, _GITHUB_CAPABILITIES):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_CAPABILITIES,
                OperationKind.INFORM,
                0.99,
                ("GitHub capability explanation",),
                (
                    (
                        "The user asked for the current GitHub authority boundary, "
                        "not a repository mutation."
                    ),
                ),
            )

        if contains_any(text, _ACCOUNT_IDENTITY):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_ACCOUNT_IDENTITY,
                OperationKind.READ,
                0.99,
                ("connected-account phrase",),
                ("The user requested authenticated GitHub identity only.",),
            )

        if contains_any(text, _REPOSITORY_INVENTORY):
            return _Decision(
                IntentDomain.GITHUB_WORKSPACE,
                GoalKind.GITHUB_REPOSITORY_INVENTORY,
                OperationKind.READ,
                0.99,
                ("repository-inventory phrase",),
                ("Repository inventory is a read-only GitHub account operation.",),
            )

        if github_context and contains_any(text, _ACTIONS):
            return self._repository_decision(
                GoalKind.GITHUB_ACTIONS_INSPECT,
                OperationKind.READ,
                "GitHub Actions inspection",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _PULL_REQUESTS):
            return self._repository_decision(
                GoalKind.GITHUB_PULL_REQUESTS_LIST,
                OperationKind.READ,
                "pull-request inspection",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _ISSUES):
            return self._repository_decision(
                GoalKind.GITHUB_ISSUES_LIST,
                OperationKind.READ,
                "issue inspection",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _COMMITS):
            return self._repository_decision(
                GoalKind.GITHUB_COMMITS_LIST,
                OperationKind.READ,
                "commit-history inspection",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _IMPORTANT_FILES):
            return self._repository_decision(
                GoalKind.GITHUB_IMPORTANT_FILES,
                OperationKind.READ,
                "important-file analysis",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _BUILD_PLAN):
            return self._repository_decision(
                GoalKind.GITHUB_BUILD_PLAN,
                OperationKind.PLAN,
                "build-plan generation",
                repository_full_name,
                repository_name,
            )

        if github_context and (
            contains_any(text, _BUILD_EXECUTE)
            or text.startswith(("build ", "please build "))
        ):
            return self._repository_decision(
                GoalKind.GITHUB_BUILD_EXECUTE,
                OperationKind.EXECUTE,
                "repository-controlled build execution",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _REPOSITORY_ANALYZE):
            return self._repository_decision(
                GoalKind.GITHUB_REPOSITORY_ANALYZE,
                OperationKind.READ,
                "repository source analysis",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _REPOSITORY_INSPECT):
            return self._repository_decision(
                GoalKind.GITHUB_REPOSITORY_INSPECT,
                OperationKind.READ,
                "repository metadata inspection",
                repository_full_name,
                repository_name,
            )

        if github_context and contains_any(text, _REPOSITORY_GENERAL_READ):
            return self._repository_decision(
                GoalKind.GITHUB_REPOSITORY_INSPECT,
                OperationKind.READ,
                "general repository inspection",
                repository_full_name,
                repository_name,
                confidence=0.79,
            )

        if github_context and contains_any(text, _CHANGE_REQUESTS):
            return self._repository_decision(
                GoalKind.GITHUB_PREPARE_CHANGE,
                OperationKind.WRITE,
                "repository change request",
                repository_full_name,
                repository_name,
            )

        if contains_any(text, _LOCAL_WORKSPACE):
            return _Decision(
                IntentDomain.LOCAL_WORKSPACE,
                GoalKind.LOCAL_WORKSPACE_STATUS,
                OperationKind.READ,
                0.98,
                ("explicit local-workspace phrase",),
                ("The request explicitly targets the local Nexuss checkout.",),
            )

        if contains_any(text, _SYSTEM_HEALTH):
            return _Decision(
                IntentDomain.SYSTEM,
                GoalKind.SYSTEM_HEALTH,
                OperationKind.READ,
                0.98,
                ("system-health phrase",),
                ("The existing system-health capability remains authoritative.",),
            )

        if text in _SMALL_TALK or any(
            text.startswith(f"{phrase} ") for phrase in _SMALL_TALK
        ):
            return _Decision(
                IntentDomain.ASSISTANT,
                GoalKind.ASSISTANT_CONVERSATION,
                OperationKind.INFORM,
                0.97,
                ("conversational phrase",),
                ("The instruction is conversational and has no side effect.",),
            )

        if contains_any(text, _DATETIME):
            return _Decision(
                IntentDomain.ASSISTANT,
                GoalKind.ASSISTANT_CONVERSATION,
                OperationKind.INFORM,
                0.96,
                ("date-or-time question",),
                ("The established conversation plane will answer it.",),
            )

        if contains_any(text, _CAPABILITIES):
            return _Decision(
                IntentDomain.ASSISTANT,
                GoalKind.ASSISTANT_CAPABILITIES,
                OperationKind.INFORM,
                0.98,
                ("capability question",),
                ("The request asks for an explanation, not an action.",),
            )

        if contains_any(text, _ARCHIVE):
            return _Decision(
                IntentDomain.ARCHIVE,
                GoalKind.ARCHIVE_PUBLISH,
                OperationKind.WRITE,
                0.96,
                ("archive-publication language",),
                ("Existing archive intake remains the authoritative workflow.",),
            )

        if contains_any(text, _NOTE):
            return _Decision(
                IntentDomain.NOTES,
                GoalKind.NOTE_CREATE,
                OperationKind.WRITE,
                0.96,
                ("managed-note phrase",),
                ("Existing managed-note planning remains authoritative.",),
            )

        if contains_any(text, _MEMORY):
            return _Decision(
                IntentDomain.MEMORY,
                GoalKind.MEMORY_ACTION,
                OperationKind.WRITE,
                0.94,
                ("memory command",),
                ("Existing memory policy remains authoritative.",),
            )

        if contains_any(text, _DEVICE):
            return _Decision(
                IntentDomain.DEVICE,
                GoalKind.DEVICE_ACTION,
                OperationKind.EXECUTE,
                0.94,
                ("device command",),
                ("Existing device policy remains authoritative.",),
            )

        if contains_any(text, _MEDIA):
            return _Decision(
                IntentDomain.MEDIA,
                GoalKind.MEDIA_DISCOVER,
                OperationKind.READ,
                0.93,
                ("media command",),
                ("Existing media capability remains authoritative.",),
            )

        if contains_any(text, _DEPLOY):
            if "plan" in text or "prepare" in text:
                return _Decision(
                    IntentDomain.DEPLOYMENT,
                    GoalKind.DEPLOYMENT_PLAN,
                    OperationKind.PLAN,
                    0.76,
                    ("deployment planning language",),
                    ("A deployment target is still required.",),
                    ("deployment_target",),
                )
            return _Decision(
                IntentDomain.DEPLOYMENT,
                GoalKind.DEPLOYMENT_EXECUTE,
                OperationKind.EXECUTE,
                0.58,
                ("deployment language without target",),
                ("Deployment environment and release target are ambiguous.",),
                ("deployment_target",),
            )

        if contains_any(text, _RESEARCH):
            return _Decision(
                IntentDomain.KNOWLEDGE,
                GoalKind.KNOWLEDGE_RESEARCH,
                OperationKind.READ,
                0.94,
                ("explicit research request",),
                ("The request explicitly asks for read-only knowledge acquisition.",),
            )

        if text.endswith("?"):
            return _Decision(
                IntentDomain.KNOWLEDGE,
                GoalKind.KNOWLEDGE_RESEARCH,
                OperationKind.READ,
                0.88,
                ("explicit question form",),
                ("The user asked a direct informational question.",),
            )

        if text in _AMBIGUOUS or any(phrase in text for phrase in _AMBIGUOUS):
            return _Decision(
                IntentDomain.AMBIGUOUS,
                GoalKind.AMBIGUOUS_REFERENCE,
                OperationKind.READ,
                0.25,
                ("unresolved pronoun or scope",),
                ("The object or desired outcome is not identified.",),
                ("target", "desired_outcome"),
            )

        return _Decision(
            IntentDomain.AMBIGUOUS,
            GoalKind.UNKNOWN,
            OperationKind.READ,
            0.0,
            ("no deterministic route matched",),
            ("Nexuss must clarify rather than guess.",),
            ("desired_outcome",),
        )

    @staticmethod
    def _constraint_conflicts(
        operation: OperationKind,
        constraints: GoalConstraints,
    ) -> tuple[str, ...]:
        conflicts: list[str] = []
        allow_modification = bool(
            getattr(constraints, "allow_modification", True)
        )
        allow_code_execution = bool(
            getattr(constraints, "allow_code_execution", True)
        )
        if (
            operation in {OperationKind.WRITE, OperationKind.DESTRUCTIVE}
            and not allow_modification
        ):
            conflicts.append("write_conflicts_with_read_only")
        if (
            operation is OperationKind.EXECUTE
            and not allow_code_execution
        ):
            conflicts.append("execution_conflicts_with_no_execution")
        return tuple(conflicts)

    @staticmethod
    def _repository_decision(
        goal: GoalKind,
        operation: OperationKind,
        label: str,
        repository_full_name: str | None,
        repository_name: str | None,
        *,
        confidence: float = 0.98,
    ) -> _Decision:
        missing = ()
        resolved_confidence = confidence
        rationale = [f"The request maps to {label}."]

        if repository_full_name is None:
            missing = ("repository",)
            resolved_confidence = min(confidence, 0.72)
            if repository_name is None:
                rationale.append("The target repository is not explicit.")
            else:
                rationale.append(
                    "A repository name was provided without an owner; "
                    "authorized inventory selection is required."
                )

        return _Decision(
            IntentDomain.GITHUB_WORKSPACE,
            goal,
            operation,
            resolved_confidence,
            (label,),
            tuple(rationale),
            missing,
        )

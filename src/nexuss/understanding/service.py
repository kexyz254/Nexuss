"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.


Deterministic front-door understanding, clarification, and safe-read dispatch.
"""

from __future__ import annotations

from uuid import UUID

from nexuss.understanding.clarification import (
    ClarificationSessionError,
    ClarificationStore,
)
from nexuss.understanding.classifier import GoalClassifier
from nexuss.understanding.commitment_executor import (
    CommitmentGoalExecutionError,
    CommitmentGoalExecutor,
)
from nexuss.understanding.context import (
    GoalContextRecord,
    GoalContextStore,
    apply_repository_context,
)
from nexuss.understanding.executor import (
    GitHubGoalExecutionError,
    GitHubReadOnlyGoalExecutor,
)
from nexuss.understanding.models import (
    ClarificationAnswer,
    ClarificationKind,
    ClarificationOption,
    DispatchKind,
    GoalInterpretation,
    GoalKind,
    IntentDomain,
    OperationKind,
    ResolutionStatus,
    UnderstandingRequest,
    UnderstandingResponse,
)


class GoalUnderstandingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_COMMITMENT_READ_GOALS = {
    GoalKind.GOOGLE_WORKSPACE_STATUS,
    GoalKind.COMMITMENT_PREPARE_DAY,
    GoalKind.COMMITMENT_LIST,
    GoalKind.COMMUNICATION_NEEDS_REPLY,
    GoalKind.CALENDAR_CONFLICTS,
}
_COMMITMENT_BLOCKED_GOALS = {
    GoalKind.COMMUNICATION_EXTERNAL_WRITE,
}

_GITHUB_READ_GOALS = {
    GoalKind.GITHUB_CAPABILITIES,
    GoalKind.GITHUB_ACCOUNT_IDENTITY,
    GoalKind.GITHUB_REPOSITORY_INVENTORY,
    GoalKind.GITHUB_REPOSITORY_INSPECT,
    GoalKind.GITHUB_REPOSITORY_ANALYZE,
    GoalKind.GITHUB_IMPORTANT_FILES,
    GoalKind.GITHUB_BUILD_PLAN,
    GoalKind.GITHUB_COMMITS_LIST,
    GoalKind.GITHUB_PULL_REQUESTS_LIST,
    GoalKind.GITHUB_ISSUES_LIST,
    GoalKind.GITHUB_ACTIONS_INSPECT,
}
_GITHUB_BLOCKED_GOALS = {
    GoalKind.GITHUB_BUILD_EXECUTE,
    GoalKind.GITHUB_PREPARE_CHANGE,
    GoalKind.GITHUB_PUSH_DIRECT_MAIN,
    GoalKind.GITHUB_APPROVAL_BYPASS,
    GoalKind.GITHUB_DELETE_REPOSITORY,
}
_LEGACY_DOMAINS = {
    IntentDomain.ASSISTANT,
    IntentDomain.LOCAL_WORKSPACE,
    IntentDomain.KNOWLEDGE,
    IntentDomain.MEDIA,
    IntentDomain.NOTES,
    IntentDomain.MEMORY,
    IntentDomain.DEVICE,
    IntentDomain.ARCHIVE,
    IntentDomain.SYSTEM,
}


class GoalUnderstandingService:
    """Interpret once, clarify when needed, then dispatch only within policy."""

    def __init__(
        self,
        *,
        github_executor: GitHubReadOnlyGoalExecutor | None = None,
        commitment_executor: CommitmentGoalExecutor | None = None,
        classifier: GoalClassifier | None = None,
        context: GoalContextStore | None = None,
        clarifications: ClarificationStore | None = None,
    ) -> None:
        self._github = github_executor
        self._commitments = commitment_executor
        self._classifier = classifier or GoalClassifier()
        self._context = context or GoalContextStore()
        self._clarifications = clarifications or ClarificationStore()

    @classmethod
    def from_environment(
        cls,
        *,
        commitment_executor: CommitmentGoalExecutor | None = None,
    ) -> GoalUnderstandingService:
        try:
            from nexuss.connectors.github.workspace_control import (
                GitHubWorkspaceControlPlane,
            )
        except ImportError:
            return cls(commitment_executor=commitment_executor)
        try:
            plane = GitHubWorkspaceControlPlane.from_environment()
        except Exception:  # noqa: BLE001 - optional connector startup boundary
            return cls(commitment_executor=commitment_executor)
        return cls(
            github_executor=GitHubReadOnlyGoalExecutor(plane),
            commitment_executor=commitment_executor,
        )

    @property
    def github_read_only_available(self) -> bool:
        return self._github is not None

    @property
    def commitment_read_only_available(self) -> bool:
        return self._commitments is not None

    def resolve(
        self,
        request: UnderstandingRequest,
        *,
        session_id: UUID,
    ) -> UnderstandingResponse:
        interpretation = self._classifier.classify(request.utterance)
        active_repository, active_ref = self._context.active_repository(session_id)
        interpretation = apply_repository_context(
            interpretation,
            active_repository,
            active_ref,
        )
        return self._route(
            request=request,
            session_id=session_id,
            interpretation=interpretation,
        )

    def answer_clarification(
        self,
        clarification_id: UUID,
        answer: ClarificationAnswer,
        *,
        session_id: UUID,
    ) -> UnderstandingResponse:
        try:
            pending, option = self._clarifications.answer(
                clarification_id,
                session_id=session_id,
                option_id=answer.option_id,
            )
        except ClarificationSessionError as exc:
            raise GoalUnderstandingError(str(exc), str(exc)) from exc

        interpretation = pending.interpretation
        field = pending.question.field_name

        if option.value.casefold() == "cancel":
            return UnderstandingResponse(
                request_id=pending.request_id,
                session_id=session_id,
                status=ResolutionStatus.CANCELLED,
                interpretation=interpretation,
                assistant_message="Clarification cancelled. No action was performed.",
            )

        if field == "repository":
            repository_full_name = option.value
            owner, repository = repository_full_name.split("/", 1)
            entities = interpretation.entities.model_copy(
                update={
                    "owner": owner,
                    "repository": repository,
                    "repository_full_name": repository_full_name,
                }
            )
            interpretation = interpretation.model_copy(
                update={
                    "entities": entities,
                    "missing_fields": tuple(
                        value
                        for value in interpretation.missing_fields
                        if value != "repository"
                    ),
                    "confidence": max(interpretation.confidence, 0.93),
                    "rationale": (
                        *interpretation.rationale,
                        "Repository selected explicitly through clarification.",
                    ),
                }
            )

        elif field == "confirm_intent":
            if option.value.casefold() == "no":
                return self._ask_scope(
                    pending.request_id,
                    session_id,
                    interpretation.model_copy(
                        update={
                            "domain": IntentDomain.AMBIGUOUS,
                            "goal": GoalKind.AMBIGUOUS_SCOPE,
                            "confidence": 0.2,
                        }
                    ),
                )
            interpretation = interpretation.model_copy(
                update={
                    "confidence": max(interpretation.confidence, 0.90),
                    "rationale": (
                        *interpretation.rationale,
                        "User confirmed the inferred intent.",
                    ),
                }
            )

        elif field == "constraint_conflict":
            if option.value == "no":
                return UnderstandingResponse(
                    request_id=pending.request_id,
                    session_id=session_id,
                    status=ResolutionStatus.CANCELLED,
                    interpretation=interpretation,
                    assistant_message=(
                        "The conflicting request was cancelled. "
                        "No action was performed."
                    ),
                )
            if (
                "execution_conflicts_with_no_execution"
                in interpretation.constraint_conflicts
            ):
                interpretation = interpretation.model_copy(
                    update={
                        "goal": GoalKind.GITHUB_BUILD_PLAN,
                        "operation": OperationKind.PLAN,
                        "constraint_conflicts": (),
                        "confidence": 0.96,
                    }
                )
            else:
                interpretation = interpretation.model_copy(
                    update={
                        "goal": GoalKind.GITHUB_REPOSITORY_ANALYZE,
                        "operation": OperationKind.READ,
                        "constraint_conflicts": (),
                        "confidence": 0.96,
                    }
                )

        elif field == "desired_outcome":
            interpretation = self._apply_outcome_choice(
                interpretation,
                option.value,
            )

        elif field == "deployment_target":
            if option.value == "plan":
                interpretation = interpretation.model_copy(
                    update={
                        "goal": GoalKind.DEPLOYMENT_PLAN,
                        "operation": OperationKind.PLAN,
                        "confidence": 0.92,
                        "missing_fields": (),
                    }
                )
            elif option.value in {"staging", "production"}:
                entities = interpretation.entities.model_copy(
                    update={"selected_object": option.value}
                )
                interpretation = interpretation.model_copy(
                    update={
                        "goal": GoalKind.DEPLOYMENT_EXECUTE,
                        "operation": OperationKind.EXECUTE,
                        "entities": entities,
                        "confidence": 0.92,
                        "missing_fields": (),
                    }
                )

        if option.value.startswith("rephrase_"):
            topic = option.value.removeprefix("rephrase_").replace("_", " ")
            return UnderstandingResponse(
                request_id=pending.request_id,
                session_id=session_id,
                status=ResolutionStatus.READY,
                interpretation=interpretation,
                assistant_message=(
                    f"The {topic} domain is selected. Restate the instruction "
                    "with the exact topic, object, or outcome. "
                    "No action was performed."
                ),
            )

        synthetic_request = UnderstandingRequest(
            request_id=pending.request_id,
            utterance=interpretation.original_utterance,
            execute_safe_reads=True,
        )
        return self._route(
            request=synthetic_request,
            session_id=session_id,
            interpretation=interpretation,
        )

    def cancel_clarification(
        self,
        clarification_id: UUID,
        *,
        session_id: UUID,
    ) -> None:
        try:
            self._clarifications.cancel(
                clarification_id,
                session_id=session_id,
            )
        except ClarificationSessionError as exc:
            raise GoalUnderstandingError(str(exc), str(exc)) from exc

    def _route(
        self,
        *,
        request: UnderstandingRequest,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        if interpretation.constraint_conflicts:
            return self._ask_constraint_resolution(
                request.request_id,
                session_id,
                interpretation,
            )

        if (
            not interpretation.constraints.allow_network_access
            and interpretation.domain
            in {
                IntentDomain.GITHUB_WORKSPACE,
                IntentDomain.KNOWLEDGE,
                IntentDomain.MEDIA,
            }
        ):
            return self._blocked(
                request,
                session_id,
                interpretation,
                message=(
                    "I preserved your no-network constraint. This request "
                    "requires an external read, so nothing was contacted "
                    "or executed."
                ),
            )

        if interpretation.goal in _COMMITMENT_BLOCKED_GOALS:
            return self._blocked(
                request,
                session_id,
                interpretation,
                message=(
                    "I understood the requested external communication or "
                    "calendar change. P6.8A can read, correlate, and prepare "
                    "the exact plan, but provider writes are disabled. "
                    "No email, message, contact, or calendar event was changed."
                ),
            )

        if interpretation.goal in {
            GoalKind.GITHUB_APPROVAL_BYPASS,
            GoalKind.GITHUB_PUSH_DIRECT_MAIN,
            GoalKind.GITHUB_DELETE_REPOSITORY,
        }:
            return self._blocked(request, session_id, interpretation)

        if interpretation.goal is GoalKind.GITHUB_BUILD_EXECUTE:
            return self._blocked(
                request,
                session_id,
                interpretation,
                message=(
                    "I understood this as a request to execute repository-controlled "
                    "build and test commands. P6.6B can prepare the exact build plan, "
                    "but trusted-local execution is not authorized through the "
                    "understanding gateway. No command or GitHub write was performed."
                ),
            )

        if interpretation.goal is GoalKind.GITHUB_PREPARE_CHANGE:
            return self._blocked(
                request,
                session_id,
                interpretation,
                message=(
                    "I understood this as a GitHub repository change request. "
                    "P6.6B may inspect and analyze the repository, but modification, "
                    "branch pushing, and pull-request creation remain disabled until "
                    "the controlled change milestone. No file or GitHub resource was changed."
                ),
            )

        if "repository" in interpretation.missing_fields:
            return self._ask_repository(
                request.request_id,
                session_id,
                interpretation,
            )

        if interpretation.domain is IntentDomain.DEPLOYMENT:
            if "deployment_target" in interpretation.missing_fields:
                return self._ask_deployment_target(
                    request.request_id,
                    session_id,
                    interpretation,
                )
            return self._blocked(
                request,
                session_id,
                interpretation,
                message=(
                    "The deployment target is now clear, but deployment execution "
                    "is not enabled in P6.6B. No release, merge, tag, or deployment "
                    "was performed."
                ),
            )

        if (
            interpretation.domain is IntentDomain.AMBIGUOUS
            or interpretation.confidence < 0.60
        ):
            return self._ask_scope(
                request.request_id,
                session_id,
                interpretation,
            )

        if 0.60 <= interpretation.confidence < 0.85:
            return self._ask_confirmation(
                request.request_id,
                session_id,
                interpretation,
            )

        if interpretation.goal in _COMMITMENT_READ_GOALS:
            if not request.execute_safe_reads:
                return UnderstandingResponse(
                    request_id=request.request_id,
                    session_id=session_id,
                    status=ResolutionStatus.READY,
                    interpretation=interpretation,
                    dispatch=DispatchKind.COMMITMENT_READ_ONLY,
                    assistant_message=(
                        "I resolved this as a read-only commitment request. "
                        "No read was executed because safe-read dispatch was disabled."
                    ),
                )
            if self._commitments is None:
                return self._blocked(
                    request,
                    session_id,
                    interpretation,
                    message=(
                        "I understood the commitment goal, but the P6.8A "
                        "service is unavailable. No external source was contacted."
                    ),
                )
            try:
                execution = self._commitments.execute(interpretation)
            except CommitmentGoalExecutionError as exc:
                return self._blocked(
                    request,
                    session_id,
                    interpretation,
                    message=exc.message,
                )
            return UnderstandingResponse(
                request_id=request.request_id,
                session_id=session_id,
                status=ResolutionStatus.COMPLETED,
                interpretation=interpretation,
                dispatch=DispatchKind.COMMITMENT_READ_ONLY,
                assistant_message=execution.assistant_message,
                execution=execution,
                no_action_performed=False,
            )

        if interpretation.goal in _GITHUB_READ_GOALS:
            if not request.execute_safe_reads:
                return UnderstandingResponse(
                    request_id=request.request_id,
                    session_id=session_id,
                    status=ResolutionStatus.READY,
                    interpretation=interpretation,
                    dispatch=DispatchKind.GITHUB_READ_ONLY,
                    assistant_message=(
                        "I resolved this as a read-only GitHub workspace request. "
                        "No operation was executed because safe-read dispatch was disabled."
                    ),
                )
            if self._github is None:
                return self._blocked(
                    request,
                    session_id,
                    interpretation,
                    message=(
                        "I understood the GitHub read-only goal, but the P6.6A "
                        "workspace control plane is not available in this runtime. "
                        "No GitHub operation was performed."
                    ),
                )
            try:
                execution = self._github.execute(interpretation)
            except GitHubGoalExecutionError as exc:
                return self._blocked(
                    request,
                    session_id,
                    interpretation,
                    message=f"{exc.message} No GitHub write was performed.",
                )
            except Exception as exc:  # noqa: BLE001 - fail-closed provider boundary
                return self._blocked(
                    request,
                    session_id,
                    interpretation,
                    message=(
                        "The read-only GitHub operation failed closed. "
                        f"{type(exc).__name__} was recorded without exposing credentials. "
                        "No GitHub write was performed."
                    ),
                )
            repository = interpretation.entities.repository_full_name
            if repository:
                self._context.append(
                    session_id,
                    GoalContextRecord(
                        interpretation=interpretation,
                        selected_repository=repository,
                        selected_ref=interpretation.entities.ref,
                    ),
                )
            return UnderstandingResponse(
                request_id=request.request_id,
                session_id=session_id,
                status=ResolutionStatus.COMPLETED,
                interpretation=interpretation,
                dispatch=DispatchKind.GITHUB_READ_ONLY,
                assistant_message=execution.assistant_message,
                execution=execution,
                no_action_performed=(
                    interpretation.operation is OperationKind.INFORM
                ),
            )

        if interpretation.domain in _LEGACY_DOMAINS:
            return UnderstandingResponse(
                request_id=request.request_id,
                session_id=session_id,
                status=ResolutionStatus.PASS_THROUGH,
                interpretation=interpretation,
                dispatch=DispatchKind.LEGACY_TASK,
                assistant_message=(
                    "Intent resolved. The existing Nexuss task plane remains "
                    "authoritative for this capability."
                ),
                resolved_utterance=self._legacy_dispatch_utterance(
                    interpretation
                ),
            )

        return self._ask_scope(
            request.request_id,
            session_id,
            interpretation,
        )

    def _ask_repository(
        self,
        request_id: UUID,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        options: list[ClarificationOption] = []
        if self._github is not None:
            try:
                for index, repository in enumerate(
                    self._github.repositories()[:12],
                    start=1,
                ):
                    full_name = str(repository.get("full_name", "")).strip()
                    if not full_name:
                        continue
                    visibility = "private" if repository.get("private") else "public"
                    options.append(
                        ClarificationOption(
                            option_id=f"repository-{index}",
                            label=full_name,
                            value=full_name,
                            description=visibility,
                        )
                    )
            except Exception:  # noqa: BLE001 - optional inventory boundary
                options = []

        if not options:
            return UnderstandingResponse(
                request_id=request_id,
                session_id=session_id,
                status=ResolutionStatus.BLOCKED,
                interpretation=interpretation,
                assistant_message=(
                    "I understood the GitHub operation, but no authorized "
                    "repository inventory is available for selection. Connect "
                    "or restore the GitHub read-only workspace, then try again. "
                    "No GitHub operation was performed."
                ),
            )

        clarification = self._clarifications.create(
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            kind=ClarificationKind.SINGLE_SELECT,
            question="Which GitHub repository should Nexuss use?",
            options=tuple(options),
            field_name="repository",
        )
        return UnderstandingResponse(
            request_id=request_id,
            session_id=session_id,
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            interpretation=interpretation,
            assistant_message=(
                "I understand the requested GitHub operation, but the target "
                "repository is not explicit. Select one repository; no action "
                "will occur until the target is clear."
            ),
            clarification=clarification,
        )

    def _ask_constraint_resolution(
        self,
        request_id: UUID,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        if (
            "execution_conflicts_with_no_execution"
            in interpretation.constraint_conflicts
        ):
            question = (
                "You requested execution but also prohibited running code. "
                "Prepare a plan only?"
            )
        else:
            question = (
                "You requested a change but also prohibited modification. "
                "Investigate read-only instead?"
            )

        clarification = self._clarifications.create(
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            kind=ClarificationKind.YES_NO,
            question=question,
            options=(
                ClarificationOption(
                    option_id="yes",
                    label="Yes",
                    value="yes",
                ),
                ClarificationOption(
                    option_id="no",
                    label="No, cancel",
                    value="no",
                ),
            ),
            field_name="constraint_conflict",
        )
        return UnderstandingResponse(
            request_id=request_id,
            session_id=session_id,
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            interpretation=interpretation,
            assistant_message=(
                "The requested action conflicts with an explicit safety "
                "constraint. Nexuss will not choose which instruction "
                "to ignore."
            ),
            clarification=clarification,
        )

    def _ask_confirmation(
        self,
        request_id: UUID,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        clarification = self._clarifications.create(
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            kind=ClarificationKind.YES_NO,
            question=(
                "Did you mean: "
                f"{self._intent_label(interpretation)}?"
            ),
            options=(
                ClarificationOption(
                    option_id="yes",
                    label="Yes",
                    value="yes",
                ),
                ClarificationOption(
                    option_id="no",
                    label="No",
                    value="no",
                ),
            ),
            field_name="confirm_intent",
        )
        return UnderstandingResponse(
            request_id=request_id,
            session_id=session_id,
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            interpretation=interpretation,
            assistant_message=(
                "The likely intent is identifiable, but confidence is below "
                "the automatic-action threshold. Confirm or reject it."
            ),
            clarification=clarification,
        )

    def _ask_scope(
        self,
        request_id: UUID,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        clarification = self._clarifications.create(
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            kind=ClarificationKind.SINGLE_SELECT,
            question="What outcome should Nexuss work toward?",
            options=(
                ClarificationOption(
                    option_id="inspect-github",
                    label="Inspect a GitHub repository",
                    value="github_inspect",
                    description="Read-only metadata and current commit.",
                ),
                ClarificationOption(
                    option_id="analyze-github",
                    label="Analyze a GitHub repository",
                    value="github_analyze",
                    description="Immutable snapshot and static analysis.",
                ),
                ClarificationOption(
                    option_id="inspect-local",
                    label="Inspect this local workspace",
                    value="local_workspace",
                    description="Use the existing local workspace capability.",
                ),
                ClarificationOption(
                    option_id="research",
                    label="Research or answer a question",
                    value="rephrase_research",
                    description="Restate the exact topic or question.",
                ),
                ClarificationOption(
                    option_id="media",
                    label="Find or play media",
                    value="rephrase_media",
                    description="Restate the subject, title, or creator.",
                ),
                ClarificationOption(
                    option_id="note",
                    label="Create a managed note",
                    value="rephrase_note",
                    description="Restate the note title and content.",
                ),
                ClarificationOption(
                    option_id="device",
                    label="Use a trusted device or application",
                    value="rephrase_device_action",
                    description=(
                        "Restate the exact device and intended action."
                    ),
                ),
                ClarificationOption(
                    option_id="cancel",
                    label="Cancel",
                    value="cancel",
                    description="No action will be performed.",
                ),
            ),
            field_name="desired_outcome",
        )
        return UnderstandingResponse(
            request_id=request_id,
            session_id=session_id,
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            interpretation=interpretation,
            assistant_message=(
                "The instruction does not identify a sufficiently clear target "
                "and outcome. Select the intended result; Nexuss will not guess."
            ),
            clarification=clarification,
        )

    def _ask_deployment_target(
        self,
        request_id: UUID,
        session_id: UUID,
        interpretation: GoalInterpretation,
    ) -> UnderstandingResponse:
        clarification = self._clarifications.create(
            session_id=session_id,
            request_id=request_id,
            interpretation=interpretation,
            kind=ClarificationKind.SINGLE_SELECT,
            question="What deployment outcome do you mean?",
            options=(
                ClarificationOption(
                    option_id="deployment-plan",
                    label="Prepare a deployment plan only",
                    value="plan",
                ),
                ClarificationOption(
                    option_id="deployment-staging",
                    label="Deploy to staging",
                    value="staging",
                ),
                ClarificationOption(
                    option_id="deployment-production",
                    label="Deploy to production",
                    value="production",
                ),
                ClarificationOption(
                    option_id="cancel",
                    label="Cancel",
                    value="cancel",
                ),
            ),
            field_name="deployment_target",
        )
        return UnderstandingResponse(
            request_id=request_id,
            session_id=session_id,
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            interpretation=interpretation,
            assistant_message=(
                "Deployment requires an explicit environment and outcome. "
                "Select one option; no deployment has occurred."
            ),
            clarification=clarification,
        )

    def _apply_outcome_choice(
        self,
        interpretation: GoalInterpretation,
        value: str,
    ) -> GoalInterpretation:
        if value == "github_inspect":
            return interpretation.model_copy(
                update={
                    "domain": IntentDomain.GITHUB_WORKSPACE,
                    "goal": GoalKind.GITHUB_REPOSITORY_INSPECT,
                    "operation": OperationKind.READ,
                    "confidence": 0.92,
                    "missing_fields": ("repository",),
                }
            )
        if value == "github_analyze":
            return interpretation.model_copy(
                update={
                    "domain": IntentDomain.GITHUB_WORKSPACE,
                    "goal": GoalKind.GITHUB_REPOSITORY_ANALYZE,
                    "operation": OperationKind.READ,
                    "confidence": 0.92,
                    "missing_fields": ("repository",),
                }
            )
        if value == "local_workspace":
            return interpretation.model_copy(
                update={
                    "domain": IntentDomain.LOCAL_WORKSPACE,
                    "goal": GoalKind.LOCAL_WORKSPACE_STATUS,
                    "operation": OperationKind.READ,
                    "confidence": 0.96,
                    "missing_fields": (),
                }
            )
        return interpretation

    @staticmethod
    def _legacy_dispatch_utterance(
        interpretation: GoalInterpretation,
    ) -> str:
        canonical = {
            GoalKind.LOCAL_WORKSPACE_STATUS: "Inspect this local workspace.",
            GoalKind.ASSISTANT_CAPABILITIES: "What can you do?",
        }
        return canonical.get(
            interpretation.goal,
            interpretation.original_utterance,
        )

    @staticmethod
    def _blocked(
        request: UnderstandingRequest,
        session_id: UUID,
        interpretation: GoalInterpretation,
        *,
        message: str | None = None,
    ) -> UnderstandingResponse:
        default = {
            GoalKind.GITHUB_APPROVAL_BYPASS: (
                "I understood this as a request to bypass phone approval. "
                "Approval cannot be bypassed or inferred from stored credentials. "
                "No credential was exposed and no GitHub write was attempted."
            ),
            GoalKind.GITHUB_PUSH_DIRECT_MAIN: (
                "I understood this as a direct write to the default branch. "
                "Direct default-branch writes are disabled. No file was modified "
                "and no GitHub write was attempted."
            ),
            GoalKind.GITHUB_DELETE_REPOSITORY: (
                "I understood this as a destructive repository deletion. "
                "Repository deletion is unavailable in this control plane. "
                "No GitHub resource was changed."
            ),
        }.get(
            interpretation.goal,
            "The request is outside the current authority boundary. No action was performed.",
        )
        return UnderstandingResponse(
            request_id=request.request_id,
            session_id=session_id,
            status=ResolutionStatus.BLOCKED,
            interpretation=interpretation,
            assistant_message=message or default,
        )

    @staticmethod
    def _intent_label(interpretation: GoalInterpretation) -> str:
        repository = interpretation.entities.repository_full_name
        goal = interpretation.goal.value.replace("_", " ")
        return f"{goal} for {repository}" if repository else goal

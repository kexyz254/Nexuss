"""Verified engineering-task lifecycle and review preparation."""

from __future__ import annotations

import difflib
import hashlib
import json
import mimetypes
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import (
    EngineeringRunReceipt,
    EngineeringTaskSpec,
)
from nexuss.engineering.provider_connections import (
    ProviderAccessDecision,
)
from nexuss.engineering.workspace import IsolatedWorkspace


class EngineeringLifecycleState(StrEnum):
    RECEIVED = "received"
    PROVIDER_CHECKING = "provider_checking"
    PROVIDER_BLOCKED = "provider_blocked"
    WORKSPACE_CREATED = "workspace_created"
    MODEL_RUNNING = "model_running"
    VALIDATING = "validating"
    REVIEW_READY = "review_ready"
    PUBLICATION_PREPARED = "publication_prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHING = "publishing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationSeverity(StrEnum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


class EngineeringLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    state: EngineeringLifecycleState
    summary: str = Field(min_length=1, max_length=2_000)
    evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_extensions: frozenset[str] = frozenset(
        {
            ".css",
            ".html",
            ".js",
            ".json",
            ".md",
            ".py",
            ".txt",
            ".yaml",
            ".yml",
        }
    )
    max_file_bytes: int = Field(
        default=1_000_000,
        ge=1_024,
        le=20_000_000,
    )
    max_diff_chars: int = Field(
        default=250_000,
        ge=1_000,
        le=2_000_000,
    )
    require_landing_page_contract: bool = False
    block_external_web_references: bool = False


class EngineeringValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1, max_length=120)
    passed: bool
    severity: ValidationSeverity
    detail: str = Field(min_length=1, max_length=4_000)
    path: str | None = Field(default=None, max_length=1_000)


class EngineeringValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    findings: tuple[EngineeringValidationFinding, ...]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credentials_exposed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringArtifactSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=200)


class EngineeringReviewBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    run_id: UUID
    provider_id: str
    provider_model: str
    workspace_root: str
    artifacts: tuple[EngineeringArtifactSnapshot, ...]
    validation: EngineeringValidationReport
    exact_diff: str
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_allowed: bool
    github_changed: bool = False
    published: bool = False
    credentials_exposed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringLifecycleOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    state: EngineeringLifecycleState
    message: str = Field(min_length=1, max_length=8_000)
    provider_access: ProviderAccessDecision
    events: tuple[EngineeringLifecycleEvent, ...]
    review: EngineeringReviewBundle | None = None
    workspace_created: bool
    github_changed: bool = False
    published: bool = False
    credentials_exposed: bool = False
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringRunExecutor(Protocol):
    def __call__(
        self,
        task: EngineeringTaskSpec,
        workspace: IsolatedWorkspace,
    ) -> EngineeringRunReceipt: ...


WorkspaceFactory = Callable[[], IsolatedWorkspace]


class _LandingPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_title = False
        self.has_main = False
        self.has_h1 = False
        self.has_external_script = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self.has_title = True
        elif normalized == "main":
            self.has_main = True
        elif normalized == "h1":
            self.has_h1 = True
        elif normalized == "script":
            values = {
                key.casefold(): value or ""
                for key, value in attrs
            }
            if values.get("src"):
                self.has_external_script = True


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    (
        "github_token",
        re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "provider_key",
        re.compile(
            r"\b(?:sk|ds)-[A-Za-z0-9_-]{20,}\b"
        ),
    ),
    (
        "authorization_bearer",
        re.compile(
            r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]+",
            re.IGNORECASE,
        ),
    ),
)

_EXTERNAL_MARKERS = (
    "http://",
    "https://",
    "fetch(",
    "xmlhttprequest",
    "google-analytics",
    "googletagmanager",
    "gtag(",
    "<iframe",
)


class EngineeringArtifactValidator:
    """Deterministically validate model-produced workspace artifacts."""

    def __init__(
        self,
        policy: EngineeringValidationPolicy | None = None,
    ) -> None:
        self.policy = policy or EngineeringValidationPolicy()

    def validate(
        self,
        workspace: IsolatedWorkspace,
        changed_files: tuple[str, ...],
    ) -> tuple[
        EngineeringValidationReport,
        tuple[EngineeringArtifactSnapshot, ...],
    ]:
        findings: list[EngineeringValidationFinding] = []
        artifacts: list[EngineeringArtifactSnapshot] = []
        contents: dict[str, str] = {}

        if not changed_files:
            findings.append(
                EngineeringValidationFinding(
                    check_id="changed_files_present",
                    passed=False,
                    severity=ValidationSeverity.ERROR,
                    detail=(
                        "The engineering run produced no changed files."
                    ),
                )
            )

        for relative in sorted(set(changed_files)):
            path = (workspace.root / relative).resolve()
            try:
                path.relative_to(workspace.root)
            except ValueError:
                findings.append(
                    EngineeringValidationFinding(
                        check_id="path_containment",
                        passed=False,
                        severity=ValidationSeverity.ERROR,
                        detail=(
                            "An artifact escaped the workspace boundary."
                        ),
                        path=relative,
                    )
                )
                continue

            if not path.is_file():
                findings.append(
                    EngineeringValidationFinding(
                        check_id="artifact_exists",
                        passed=False,
                        severity=ValidationSeverity.ERROR,
                        detail=(
                            "A changed artifact does not exist."
                        ),
                        path=relative,
                    )
                )
                continue

            suffix = path.suffix.casefold()
            extension_allowed = (
                suffix in self.policy.allowed_extensions
            )
            findings.append(
                EngineeringValidationFinding(
                    check_id="extension_allowed",
                    passed=extension_allowed,
                    severity=(
                        ValidationSeverity.INFORMATION
                        if extension_allowed
                        else ValidationSeverity.ERROR
                    ),
                    detail=(
                        "Artifact extension is permitted."
                        if extension_allowed
                        else "Artifact extension is not permitted."
                    ),
                    path=relative,
                )
            )

            raw = path.read_bytes()
            size_allowed = (
                len(raw) <= self.policy.max_file_bytes
            )
            findings.append(
                EngineeringValidationFinding(
                    check_id="size_limit",
                    passed=size_allowed,
                    severity=(
                        ValidationSeverity.INFORMATION
                        if size_allowed
                        else ValidationSeverity.ERROR
                    ),
                    detail=(
                        f"Artifact size is {len(raw)} bytes."
                    ),
                    path=relative,
                )
            )
            if not size_allowed:
                continue

            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                findings.append(
                    EngineeringValidationFinding(
                        check_id="utf8_text",
                        passed=False,
                        severity=ValidationSeverity.ERROR,
                        detail=(
                            "Binary artifacts are not supported "
                            "by this lifecycle checkpoint."
                        ),
                        path=relative,
                    )
                )
                continue

            contents[relative] = content
            detected = [
                pattern_id
                for pattern_id, pattern in _SECRET_PATTERNS
                if pattern.search(content)
            ]
            findings.append(
                EngineeringValidationFinding(
                    check_id="secret_scan",
                    passed=not detected,
                    severity=(
                        ValidationSeverity.INFORMATION
                        if not detected
                        else ValidationSeverity.ERROR
                    ),
                    detail=(
                        "No credential-like material was detected."
                        if not detected
                        else (
                            "Credential-like material was detected: "
                            + ", ".join(detected)
                        )
                    ),
                    path=relative,
                )
            )

            digest = hashlib.sha256(raw).hexdigest()
            media_type = (
                mimetypes.guess_type(relative)[0]
                or "text/plain"
            )
            artifacts.append(
                EngineeringArtifactSnapshot(
                    path=relative,
                    sha256=digest,
                    size_bytes=len(raw),
                    media_type=media_type,
                )
            )

        if self.policy.block_external_web_references:
            for relative, content in contents.items():
                lowered = content.casefold()
                detected = [
                    marker
                    for marker in _EXTERNAL_MARKERS
                    if marker in lowered
                ]
                findings.append(
                    EngineeringValidationFinding(
                        check_id="external_references_absent",
                        passed=not detected,
                        severity=(
                            ValidationSeverity.INFORMATION
                            if not detected
                            else ValidationSeverity.ERROR
                        ),
                        detail=(
                            "No external network references were detected."
                            if not detected
                            else (
                                "External network references were detected: "
                                + ", ".join(detected)
                            )
                        ),
                        path=relative,
                    )
                )

        if self.policy.require_landing_page_contract:
            self._validate_landing_page(contents, findings)

        passed = not any(
            not finding.passed
            and finding.severity is ValidationSeverity.ERROR
            for finding in findings
        )
        canonical = json.dumps(
            [
                finding.model_dump(mode="json")
                for finding in findings
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        report_sha256 = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        return (
            EngineeringValidationReport(
                passed=passed,
                findings=tuple(findings),
                report_sha256=report_sha256,
                credentials_exposed=False,
            ),
            tuple(sorted(artifacts, key=lambda item: item.path)),
        )

    @staticmethod
    def _validate_landing_page(
        contents: Mapping[str, str],
        findings: list[EngineeringValidationFinding],
    ) -> None:
        required = {"index.html", "styles.css"}
        available = set(contents)
        findings.append(
            EngineeringValidationFinding(
                check_id="landing_page_file_contract",
                passed=available == required,
                severity=(
                    ValidationSeverity.INFORMATION
                    if available == required
                    else ValidationSeverity.ERROR
                ),
                detail=(
                    "The landing page contains exactly index.html "
                    "and styles.css."
                    if available == required
                    else (
                        "Landing-page files differ from the exact "
                        "two-file contract."
                    )
                ),
            )
        )

        html = contents.get("index.html", "")
        css = contents.get("styles.css", "")
        parser = _LandingPageParser()
        parser.feed(html)

        checks = (
            (
                "landing_page_title",
                parser.has_title,
                "The page includes a title element.",
            ),
            (
                "landing_page_main",
                parser.has_main,
                "The page includes a main landmark.",
            ),
            (
                "landing_page_h1",
                parser.has_h1,
                "The page includes a primary heading.",
            ),
            (
                "landing_page_external_script",
                not parser.has_external_script,
                "The page contains no external script source.",
            ),
            (
                "landing_page_stylesheet_reference",
                (
                    'href="styles.css"' in html
                    or "href='styles.css'" in html
                ),
                "The page references styles.css.",
            ),
            (
                "landing_page_css_nonempty",
                bool(css.strip()),
                "The stylesheet is nonempty.",
            ),
        )
        for check_id, passed, detail in checks:
            findings.append(
                EngineeringValidationFinding(
                    check_id=check_id,
                    passed=passed,
                    severity=(
                        ValidationSeverity.INFORMATION
                        if passed
                        else ValidationSeverity.ERROR
                    ),
                    detail=detail,
                )
            )


class EngineeringTaskLifecycle:
    """Run a bounded task up to review readiness, never publication."""

    def __init__(
        self,
        *,
        validator: EngineeringArtifactValidator | None = None,
    ) -> None:
        self._validator = validator or EngineeringArtifactValidator()

    def execute(
        self,
        task: EngineeringTaskSpec,
        provider_access: ProviderAccessDecision,
        executor: EngineeringRunExecutor,
        workspace_factory: WorkspaceFactory,
        *,
        baseline_files: Mapping[str, str] | None = None,
    ) -> EngineeringLifecycleOutcome:
        events: list[EngineeringLifecycleEvent] = []
        self._event(
            events,
            EngineeringLifecycleState.RECEIVED,
            "Engineering task received.",
        )
        self._event(
            events,
            EngineeringLifecycleState.PROVIDER_CHECKING,
            "Engineering provider readiness was evaluated.",
            provider_access.model_dump_json(),
        )

        if not provider_access.available:
            self._event(
                events,
                EngineeringLifecycleState.PROVIDER_BLOCKED,
                provider_access.user_message,
            )
            return EngineeringLifecycleOutcome(
                task_id=task.task_id,
                state=EngineeringLifecycleState.PROVIDER_BLOCKED,
                message=provider_access.user_message,
                provider_access=provider_access,
                events=tuple(events),
                workspace_created=False,
                github_changed=False,
                published=False,
                credentials_exposed=False,
            )

        workspace = workspace_factory()
        self._event(
            events,
            EngineeringLifecycleState.WORKSPACE_CREATED,
            "A path-contained engineering workspace was created.",
            str(workspace.root),
        )
        self._event(
            events,
            EngineeringLifecycleState.MODEL_RUNNING,
            "The bounded engineering provider run started.",
        )

        try:
            receipt = executor(task, workspace)
        except EngineeringError as exc:
            self._event(
                events,
                EngineeringLifecycleState.FAILED,
                f"{exc.code}: {exc.message}",
            )
            return EngineeringLifecycleOutcome(
                task_id=task.task_id,
                state=EngineeringLifecycleState.FAILED,
                message=exc.message,
                provider_access=provider_access,
                events=tuple(events),
                workspace_created=True,
                github_changed=False,
                published=False,
                credentials_exposed=False,
            )

        self._event(
            events,
            EngineeringLifecycleState.VALIDATING,
            "Nexuss started independent artifact validation.",
            receipt.model_dump_json(),
        )
        report, artifacts = self._validator.validate(
            workspace,
            receipt.changed_files,
        )
        exact_diff = self._exact_diff(
            workspace,
            receipt.changed_files,
            baseline_files or {},
            self._validator.policy.max_diff_chars,
        )
        diff_sha256 = hashlib.sha256(
            exact_diff.encode("utf-8")
        ).hexdigest()

        review = EngineeringReviewBundle(
            task_id=task.task_id,
            run_id=receipt.run_id,
            provider_id=receipt.provider_id,
            provider_model=provider_access.model,
            workspace_root=str(workspace.root),
            artifacts=artifacts,
            validation=report,
            exact_diff=exact_diff,
            diff_sha256=diff_sha256,
            publication_allowed=report.passed,
            github_changed=False,
            published=False,
            credentials_exposed=False,
        )

        if not report.passed:
            self._event(
                events,
                EngineeringLifecycleState.FAILED,
                "Artifact validation failed; publication is prohibited.",
                report.model_dump_json(),
            )
            return EngineeringLifecycleOutcome(
                task_id=task.task_id,
                state=EngineeringLifecycleState.FAILED,
                message=(
                    "Engineering artifacts failed independent "
                    "validation. No publication is allowed."
                ),
                provider_access=provider_access,
                events=tuple(events),
                review=review,
                workspace_created=True,
                github_changed=False,
                published=False,
                credentials_exposed=False,
            )

        self._event(
            events,
            EngineeringLifecycleState.REVIEW_READY,
            "Validated artifacts and the exact diff are ready for review.",
            review.model_dump_json(),
        )
        return EngineeringLifecycleOutcome(
            task_id=task.task_id,
            state=EngineeringLifecycleState.REVIEW_READY,
            message=(
                "Engineering work is validated and ready for human review. "
                "No GitHub change has been made."
            ),
            provider_access=provider_access,
            events=tuple(events),
            review=review,
            workspace_created=True,
            github_changed=False,
            published=False,
            credentials_exposed=False,
        )

    @staticmethod
    def _event(
        events: list[EngineeringLifecycleEvent],
        state: EngineeringLifecycleState,
        summary: str,
        evidence: str | None = None,
    ) -> None:
        digest = (
            hashlib.sha256(evidence.encode("utf-8")).hexdigest()
            if evidence is not None
            else None
        )
        events.append(
            EngineeringLifecycleEvent(
                sequence=len(events) + 1,
                state=state,
                summary=summary,
                evidence_sha256=digest,
            )
        )

    @staticmethod
    def _exact_diff(
        workspace: IsolatedWorkspace,
        changed_files: tuple[str, ...],
        baseline_files: Mapping[str, str],
        max_chars: int,
    ) -> str:
        chunks: list[str] = []
        for relative in sorted(set(changed_files)):
            after = workspace.read_text(relative)
            before = baseline_files.get(relative, "")
            chunks.extend(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=(
                        f"a/{relative}"
                        if relative in baseline_files
                        else "/dev/null"
                    ),
                    tofile=f"b/{relative}",
                    lineterm="\n",
                )
            )
        diff = "".join(chunks)
        if len(diff) > max_chars:
            raise EngineeringError(
                "ENGINEERING_DIFF_TOO_LARGE",
                "The exact engineering diff exceeds its review budget.",
            )
        return diff


def default_lifecycle_workspace_factory() -> IsolatedWorkspace:
    """Create a persistent local review workspace for a lifecycle run."""

    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise EngineeringError(
            "ENGINEERING_LOCAL_APP_DATA_UNAVAILABLE",
            "The local application-data directory is unavailable.",
        )
    root = (
        Path(local_app_data)
        / "Nexuss"
        / "engineering-runs"
        / f"task-{uuid4()}"
    )
    return IsolatedWorkspace(root)

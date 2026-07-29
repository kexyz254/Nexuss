"""Phone-approval-bound publication of a verified archive to an empty repository."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.models import (
    GitHubAccount,
    GitHubRepository,
    VerifiedRepositoryCreate,
)
from nexuss.engineering.archive_intake import ArchiveIntakeReceipt
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportProposal,
)

_GIT_SHA = r"^[0-9a-f]{40}$"
_SHA256 = r"^[0-9a-f]{64}$"


class ArchivePublishFile(BaseModel):
    """One exact source file bound to the publication approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)
    git_blob_sha1: str = Field(pattern=_GIT_SHA)
    size_bytes: int = Field(ge=0)
    git_mode: str = Field(pattern=r"^100(?:644|755)$")


class PreparedArchivePublish(BaseModel):
    """A publication payload that performs no GitHub write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    intake_id: UUID
    repository_creation_request_id: UUID
    repository_creation_approval_id: UUID
    repository_id: int
    owner_login: str = Field(min_length=1, max_length=100)
    repository_name: str = Field(min_length=1, max_length=100)
    branch: str = Field(min_length=1, max_length=255)
    commit_message: str = Field(min_length=1, max_length=500)
    archive_sha256: str = Field(pattern=_SHA256)
    manifest_sha256: str = Field(pattern=_SHA256)
    source_root: str
    files: tuple[ArchivePublishFile, ...]
    payload_sha256: str = Field(pattern=_SHA256)
    approval_required: bool = True
    approval_channel: str = "phone"
    force_push: bool = False
    workflow_files_changed: bool = False
    prepared_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    @model_validator(mode="after")
    def validate_contract(self) -> PreparedArchivePublish:
        if not self.files:
            raise ValueError("files must not be empty")
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("publication paths must be unique")
        if any(
            path.casefold().startswith(".github/workflows/")
            for path in paths
        ):
            raise ValueError("workflow files are prohibited")
        if self.force_push or self.workflow_files_changed:
            raise ValueError("unsafe publication flags are prohibited")
        digest = hashlib.sha256(
            canonical_archive_publish_bytes(self)
        ).hexdigest()
        if digest != self.payload_sha256:
            raise ValueError("payload_sha256 is invalid")
        return self


class ArchivePublishApproval(BaseModel):
    """Single-use approval material supplied by the Nexuss approval plane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID
    request_id: UUID
    account_login: str
    repository_name: str
    payload_sha256: str = Field(pattern=_SHA256)
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> ArchivePublishApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiry must follow approval time")
        return self


class GitTreeEntryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    mode: str
    object_type: str
    sha: str = Field(pattern=_GIT_SHA)
    size: int | None = Field(default=None, ge=0)


class VerifiedArchivePublish(BaseModel):
    """Secret-free evidence that every approved file became the initial tree."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    approval_id: UUID
    payload_sha256: str = Field(pattern=_SHA256)
    repository_id: int
    owner_login: str
    repository_name: str
    branch: str
    commit_sha: str = Field(pattern=_GIT_SHA)
    tree_sha: str = Field(pattern=_GIT_SHA)
    reference_sha: str = Field(pattern=_GIT_SHA)
    file_count: int = Field(ge=1)
    total_bytes: int = Field(ge=0)
    files: tuple[GitTreeEntryEvidence, ...]
    repository_private_verified: bool
    repository_owner_verified: bool
    repository_name_verified: bool
    repository_was_empty_verified: bool
    branch_verified: bool
    commit_verified: bool
    tree_verified: bool
    all_files_verified: bool
    initial_commit_verified: bool
    default_branch_verified: bool
    visible_branch_created: bool
    force_push_used: bool = False
    workflow_files_changed: bool = False
    credentials_exposed: bool = False
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class GitHubArchiveApi(Protocol):
    """Narrow API surface required by the archive publisher."""

    def authenticated_user(self) -> GitHubAccount: ...

    def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubRepository: ...

    def repository_is_empty(
        self,
        owner: str,
        repository: str,
    ) -> bool: ...

    def create_git_blob(
        self,
        owner: str,
        repository: str,
        content_base64: str,
    ) -> str: ...

    def create_git_tree(
        self,
        owner: str,
        repository: str,
        entries: list[dict[str, object]],
    ) -> str: ...

    def create_git_commit(
        self,
        owner: str,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parents: list[str],
    ) -> str: ...

    def get_git_reference(
        self,
        owner: str,
        repository: str,
        reference: str,
    ) -> str | None: ...

    def create_git_reference(
        self,
        owner: str,
        repository: str,
        *,
        reference: str,
        commit_sha: str,
    ) -> str: ...

    def get_git_commit(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
    ) -> dict[str, object]: ...

    def get_git_tree(
        self,
        owner: str,
        repository: str,
        tree_sha: str,
        *,
        recursive: bool,
    ) -> dict[str, object]: ...


def git_blob_sha1(content: bytes) -> str:
    """Return the canonical Git object SHA-1 for one blob."""

    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def canonical_archive_publish_payload(
    prepared: PreparedArchivePublish,
) -> dict[str, object]:
    """Return the exact phone-approval payload without local-only paths."""

    return {
        "intake_id": str(prepared.intake_id),
        "repository_creation_request_id": str(
            prepared.repository_creation_request_id
        ),
        "repository_creation_approval_id": str(
            prepared.repository_creation_approval_id
        ),
        "repository_id": prepared.repository_id,
        "owner_login": prepared.owner_login,
        "repository_name": prepared.repository_name,
        "branch": prepared.branch,
        "commit_message": prepared.commit_message,
        "archive_sha256": prepared.archive_sha256,
        "manifest_sha256": prepared.manifest_sha256,
        "files": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "git_blob_sha1": item.git_blob_sha1,
                "size_bytes": item.size_bytes,
                "git_mode": item.git_mode,
            }
            for item in prepared.files
        ],
        "approval_required": True,
        "approval_channel": "phone",
        "force_push": False,
        "workflow_files_changed": False,
    }


def canonical_archive_publish_bytes(
    prepared: PreparedArchivePublish,
) -> bytes:
    return json.dumps(
        canonical_archive_publish_payload(prepared),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


class GitHubArchivePublisher:
    """Prepare and publish one root commit to a verified empty repository."""

    def prepare(
        self,
        receipt: ArchiveIntakeReceipt,
        proposal: ArchiveRepositoryImportProposal,
        verified_repository: VerifiedRepositoryCreate,
        *,
        now: datetime | None = None,
    ) -> PreparedArchivePublish:
        repository = verified_repository.repository
        self._validate_repository_binding(
            receipt,
            proposal,
            verified_repository,
        )

        source_root = Path(receipt.extracted_root).resolve()
        files: list[ArchivePublishFile] = []
        for entry in receipt.entries:
            source = (source_root / entry.repository_path).resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise ConnectorError(
                    "GITHUB_ARCHIVE_SOURCE_ESCAPE",
                    "An archive publication source escaped quarantine.",
                ) from exc
            if not source.is_file():
                raise ConnectorError(
                    "GITHUB_ARCHIVE_SOURCE_MISSING",
                    "An approved archive file is missing.",
                    safe_details={"path": entry.repository_path},
                )
            content = source.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if (
                digest != entry.sha256
                or len(content) != entry.size_bytes
            ):
                raise ConnectorError(
                    "GITHUB_ARCHIVE_SOURCE_CHANGED",
                    "An archive file changed after intake.",
                    safe_details={"path": entry.repository_path},
                )
            files.append(
                ArchivePublishFile(
                    path=entry.repository_path,
                    sha256=digest,
                    git_blob_sha1=git_blob_sha1(content),
                    size_bytes=len(content),
                    git_mode=entry.git_mode,
                )
            )

        provisional = PreparedArchivePublish.model_construct(
            request_id=uuid4(),
            intake_id=receipt.intake_id,
            repository_creation_request_id=(
                verified_repository.request_id
            ),
            repository_creation_approval_id=(
                verified_repository.approval_id
            ),
            repository_id=repository.repository_id,
            owner_login=repository.owner_login,
            repository_name=repository.name,
            branch=proposal.branch,
            commit_message=proposal.commit_message,
            archive_sha256=receipt.archive_sha256,
            manifest_sha256=receipt.manifest_sha256,
            source_root=str(source_root),
            files=tuple(sorted(files, key=lambda item: item.path)),
            payload_sha256="0" * 64,
            approval_required=True,
            approval_channel="phone",
            force_push=False,
            workflow_files_changed=False,
            prepared_at=now or datetime.now(UTC),
        )
        digest = hashlib.sha256(
            canonical_archive_publish_bytes(provisional)
        ).hexdigest()
        return PreparedArchivePublish(
            **provisional.model_dump(exclude={"payload_sha256"}),
            payload_sha256=digest,
        )

    def publish(
        self,
        api: GitHubArchiveApi,
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedArchivePublish:
        checked_at = now or datetime.now(UTC)
        self._validate_approval(prepared, approval, checked_at)

        account = api.authenticated_user()
        if account.login.casefold() != prepared.owner_login.casefold():
            raise ConnectorError(
                "GITHUB_ARCHIVE_ACCOUNT_MISMATCH",
                "The connected GitHub account changed after approval.",
            )

        repository = api.get_repository(
            prepared.owner_login,
            prepared.repository_name,
        )
        self._validate_live_repository(prepared, repository)
        was_empty = api.repository_is_empty(
            prepared.owner_login,
            prepared.repository_name,
        )
        if not was_empty:
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_NOT_EMPTY",
                "Archive publication is limited to an empty repository.",
            )

        reference_name = f"heads/{prepared.branch}"
        existing_reference = api.get_git_reference(
            prepared.owner_login,
            prepared.repository_name,
            reference_name,
        )
        if existing_reference is not None:
            raise ConnectorError(
                "GITHUB_ARCHIVE_BRANCH_ALREADY_EXISTS",
                "The approved initial branch already exists.",
            )

        source_root = Path(prepared.source_root).resolve()
        tree_entries: list[dict[str, object]] = []
        expected_tree: dict[str, ArchivePublishFile] = {}
        for item in prepared.files:
            content = self._read_verified_source(source_root, item)
            returned_sha = api.create_git_blob(
                prepared.owner_login,
                prepared.repository_name,
                base64.b64encode(content).decode("ascii"),
            )
            if returned_sha != item.git_blob_sha1:
                raise ConnectorError(
                    "GITHUB_ARCHIVE_BLOB_NOT_VERIFIED",
                    "GitHub returned an unexpected blob identifier.",
                    safe_details={"path": item.path},
                )
            expected_tree[item.path] = item
            tree_entries.append(
                {
                    "path": item.path,
                    "mode": item.git_mode,
                    "type": "blob",
                    "sha": returned_sha,
                }
            )

        tree_sha = api.create_git_tree(
            prepared.owner_login,
            prepared.repository_name,
            tree_entries,
        )
        commit_sha = api.create_git_commit(
            prepared.owner_login,
            prepared.repository_name,
            message=prepared.commit_message,
            tree_sha=tree_sha,
            parents=[],
        )

        reference_sha: str
        try:
            reference_sha = api.create_git_reference(
                prepared.owner_login,
                prepared.repository_name,
                reference=f"refs/{reference_name}",
                commit_sha=commit_sha,
            )
        except ConnectorError as exc:
            # A network failure after the POST is ambiguous. Do not retry the
            # write; reconcile by reading the branch.
            if not exc.retryable:
                raise
            observed = api.get_git_reference(
                prepared.owner_login,
                prepared.repository_name,
                reference_name,
            )
            if observed != commit_sha:
                raise ConnectorError(
                    "GITHUB_ARCHIVE_REFERENCE_UNCERTAIN",
                    "The branch creation result could not be reconciled.",
                    retryable=False,
                    safe_details={
                        "expected_commit_sha": commit_sha,
                        "observed_commit_sha": observed,
                    },
                ) from exc
            reference_sha = observed

        return self._verify(
            api,
            prepared,
            approval,
            repository_was_empty=was_empty,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            reference_sha=reference_sha,
            expected_tree=expected_tree,
            checked_at=checked_at,
        )

    @staticmethod
    def _validate_repository_binding(
        receipt: ArchiveIntakeReceipt,
        proposal: ArchiveRepositoryImportProposal,
        verified: VerifiedRepositoryCreate,
    ) -> None:
        repository = verified.repository
        if not receipt.publication_allowed:
            raise ConnectorError(
                "GITHUB_ARCHIVE_INTAKE_PROHIBITED",
                "The archive intake does not permit publication.",
            )
        if proposal.intake_id != receipt.intake_id:
            raise ConnectorError(
                "GITHUB_ARCHIVE_INTAKE_MISMATCH",
                "The repository proposal belongs to another archive.",
            )
        if (
            proposal.archive_sha256 != receipt.archive_sha256
            or proposal.manifest_sha256 != receipt.manifest_sha256
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_MANIFEST_MISMATCH",
                "The archive manifest changed after review.",
            )
        if (
            repository.owner_login.casefold()
            != proposal.account_login.casefold()
            or repository.name.casefold()
            != proposal.repository_name.casefold()
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_BINDING_MISMATCH",
                "The created repository differs from the approved target.",
            )
        if not (
            verified.private_verified
            and verified.owner_verified
            and verified.name_verified
            and verified.empty_repository_verified
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_NOT_VERIFIED",
                "The repository creation phase is not fully verified.",
            )
        expected_create_payload = {
            "name": proposal.repository_name,
            "private": True,
            "auto_init": False,
        }
        expected_create_hash = hashlib.sha256(
            json.dumps(
                expected_create_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if verified.payload_sha256 != expected_create_hash:
            raise ConnectorError(
                "GITHUB_ARCHIVE_CREATION_PAYLOAD_MISMATCH",
                "The verified repository creation payload is not exact.",
            )

    @staticmethod
    def _validate_approval(
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        checked_at: datetime,
    ) -> None:
        if approval.request_id != prepared.request_id:
            raise ConnectorError(
                "GITHUB_ARCHIVE_APPROVAL_REQUEST_MISMATCH",
                "The archive approval belongs to another request.",
            )
        if approval.payload_sha256 != prepared.payload_sha256:
            raise ConnectorError(
                "GITHUB_ARCHIVE_APPROVAL_PAYLOAD_MISMATCH",
                "The approved archive payload does not match.",
            )
        if (
            approval.account_login.casefold()
            != prepared.owner_login.casefold()
            or approval.repository_name.casefold()
            != prepared.repository_name.casefold()
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_APPROVAL_DESTINATION_MISMATCH",
                "The archive approval names another destination.",
            )
        if checked_at >= approval.expires_at:
            raise ConnectorError(
                "GITHUB_ARCHIVE_APPROVAL_EXPIRED",
                "The archive publication approval expired.",
            )
        if checked_at < approval.approved_at:
            raise ConnectorError(
                "GITHUB_ARCHIVE_APPROVAL_TIME_INVALID",
                "The archive approval timestamp is in the future.",
            )

    @staticmethod
    def _validate_live_repository(
        prepared: PreparedArchivePublish,
        repository: GitHubRepository,
    ) -> None:
        if repository.repository_id != prepared.repository_id:
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_ID_MISMATCH",
                "The target repository identity changed.",
            )
        if (
            not repository.private
            or repository.archived
            or repository.disabled
            or repository.fork
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_STATE_INVALID",
                "The target repository is not an active private root repository.",
            )
        if (
            repository.owner_login.casefold()
            != prepared.owner_login.casefold()
            or repository.name.casefold()
            != prepared.repository_name.casefold()
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_REPOSITORY_DESTINATION_MISMATCH",
                "The live repository differs from the approved destination.",
            )

    @staticmethod
    def _read_verified_source(
        source_root: Path,
        item: ArchivePublishFile,
    ) -> bytes:
        source = (source_root / item.path).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise ConnectorError(
                "GITHUB_ARCHIVE_SOURCE_ESCAPE",
                "An approved source path escaped quarantine.",
            ) from exc
        if not source.is_file():
            raise ConnectorError(
                "GITHUB_ARCHIVE_SOURCE_MISSING",
                "An approved source file is missing.",
                safe_details={"path": item.path},
            )
        content = source.read_bytes()
        if (
            len(content) != item.size_bytes
            or hashlib.sha256(content).hexdigest() != item.sha256
            or git_blob_sha1(content) != item.git_blob_sha1
        ):
            raise ConnectorError(
                "GITHUB_ARCHIVE_SOURCE_CHANGED",
                "An approved source file changed before publication.",
                safe_details={"path": item.path},
            )
        return content

    @staticmethod
    def _verify(
        api: GitHubArchiveApi,
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        *,
        repository_was_empty: bool,
        commit_sha: str,
        tree_sha: str,
        reference_sha: str,
        expected_tree: dict[str, ArchivePublishFile],
        checked_at: datetime,
    ) -> VerifiedArchivePublish:
        repository = api.get_repository(
            prepared.owner_login,
            prepared.repository_name,
        )
        observed_reference = api.get_git_reference(
            prepared.owner_login,
            prepared.repository_name,
            f"heads/{prepared.branch}",
        )
        commit_payload = api.get_git_commit(
            prepared.owner_login,
            prepared.repository_name,
            commit_sha,
        )
        tree_payload = api.get_git_tree(
            prepared.owner_login,
            prepared.repository_name,
            tree_sha,
            recursive=True,
        )

        commit_tree = commit_payload.get("tree")
        parents = commit_payload.get("parents")
        commit_verified = (
            isinstance(commit_tree, dict)
            and commit_tree.get("sha") == tree_sha
            and isinstance(parents, list)
            and not parents
            and commit_payload.get("sha") == commit_sha
        )

        raw_tree = tree_payload.get("tree")
        if not isinstance(raw_tree, list):
            raise ConnectorError(
                "GITHUB_ARCHIVE_TREE_RESPONSE_INVALID",
                "GitHub returned an invalid verification tree.",
            )
        if tree_payload.get("truncated") is True:
            raise ConnectorError(
                "GITHUB_ARCHIVE_TREE_TRUNCATED",
                "GitHub truncated the verification tree.",
            )

        observed: dict[str, GitTreeEntryEvidence] = {}
        for raw in raw_tree:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path", ""))
            if raw.get("type") != "blob" or path not in expected_tree:
                continue
            observed[path] = GitTreeEntryEvidence(
                path=path,
                mode=str(raw.get("mode", "")),
                object_type="blob",
                sha=str(raw.get("sha", "")),
                size=(
                    int(raw["size"])
                    if raw.get("size") is not None
                    else None
                ),
            )

        all_files_verified = len(observed) == len(expected_tree)
        if all_files_verified:
            for path, expected in expected_tree.items():
                item = observed.get(path)
                if item is None or (
                    item.mode != expected.git_mode
                    or item.sha != expected.git_blob_sha1
                    or (
                        item.size is not None
                        and item.size != expected.size_bytes
                    )
                ):
                    all_files_verified = False
                    break

        branch_verified = (
            observed_reference == commit_sha
            and reference_sha == commit_sha
        )
        tree_verified = (
            tree_payload.get("sha") == tree_sha
            and all_files_verified
        )
        repository_private_verified = repository.private is True
        repository_owner_verified = (
            repository.owner_login.casefold()
            == prepared.owner_login.casefold()
        )
        repository_name_verified = (
            repository.name.casefold()
            == prepared.repository_name.casefold()
        )
        default_branch_verified = (
            repository.default_branch == prepared.branch
        )
        initial_commit_verified = (
            commit_verified
            and branch_verified
            and repository_was_empty
        )

        checks = (
            repository_private_verified,
            repository_owner_verified,
            repository_name_verified,
            repository_was_empty,
            branch_verified,
            commit_verified,
            tree_verified,
            all_files_verified,
            initial_commit_verified,
            default_branch_verified,
        )
        if not all(checks):
            raise ConnectorError(
                "GITHUB_ARCHIVE_PUBLICATION_NOT_VERIFIED",
                "The initial archive publication failed verification.",
                safe_details={
                    "repository_private_verified": (
                        repository_private_verified
                    ),
                    "repository_owner_verified": (
                        repository_owner_verified
                    ),
                    "repository_name_verified": (
                        repository_name_verified
                    ),
                    "repository_was_empty_verified": (
                        repository_was_empty
                    ),
                    "branch_verified": branch_verified,
                    "commit_verified": commit_verified,
                    "tree_verified": tree_verified,
                    "all_files_verified": all_files_verified,
                    "initial_commit_verified": (
                        initial_commit_verified
                    ),
                    "default_branch_verified": (
                        default_branch_verified
                    ),
                },
            )

        return VerifiedArchivePublish(
            request_id=prepared.request_id,
            approval_id=approval.approval_id,
            payload_sha256=prepared.payload_sha256,
            repository_id=prepared.repository_id,
            owner_login=prepared.owner_login,
            repository_name=prepared.repository_name,
            branch=prepared.branch,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            reference_sha=reference_sha,
            file_count=len(prepared.files),
            total_bytes=sum(
                item.size_bytes for item in prepared.files
            ),
            files=tuple(
                observed[path] for path in sorted(observed)
            ),
            repository_private_verified=(
                repository_private_verified
            ),
            repository_owner_verified=repository_owner_verified,
            repository_name_verified=repository_name_verified,
            repository_was_empty_verified=repository_was_empty,
            branch_verified=branch_verified,
            commit_verified=commit_verified,
            tree_verified=tree_verified,
            all_files_verified=all_files_verified,
            initial_commit_verified=initial_commit_verified,
            default_branch_verified=default_branch_verified,
            visible_branch_created=True,
            force_push_used=False,
            workflow_files_changed=False,
            credentials_exposed=False,
            verified_at=checked_at,
        )

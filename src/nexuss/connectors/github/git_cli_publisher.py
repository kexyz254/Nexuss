"""Exact root-commit publication to a truly empty GitHub repository.

GitHub's Git References API rejects the first reference in an empty repository
with HTTP 409. This publisher constructs the approved Git object graph locally
and sends it with Git smart HTTP. The resulting branch contains one root commit
whose tree is verified independently through the GitHub API.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.archive_publisher import (
    ArchivePublishApproval,
    ArchivePublishFile,
    GitHubArchiveApi,
    GitHubArchivePublisher,
    PreparedArchivePublish,
    VerifiedArchivePublish,
    git_blob_sha1,
)


@dataclass(frozen=True)
class RootCommitPush:
    commit_sha: str
    tree_sha: str
    reference_sha: str


class GitCliArchivePublisher:
    """Publish one exact root commit without exposing the OAuth token."""

    _COMMAND_TIMEOUT_SECONDS = 120
    _VERIFY_ATTEMPTS = 8
    _VERIFY_DELAY_SECONDS = 0.75

    def publish(
        self,
        api: GitHubArchiveApi,
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        *,
        access_token: str,
        now: datetime | None = None,
        remote_url: str | None = None,
    ) -> VerifiedArchivePublish:
        checked_at = now or datetime.now(UTC)
        verifier = GitHubArchivePublisher()
        verifier._validate_approval(prepared, approval, checked_at)

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
        verifier._validate_live_repository(prepared, repository)

        was_empty = api.repository_is_empty(
            prepared.owner_login,
            prepared.repository_name,
        )
        expected_tree = {
            item.path: item for item in prepared.files
        }

        # NEXUSS_IDEMPOTENT_ARCHIVE_PUBLISH_V2
        if was_empty:
            # Do not query Git refs before the first push. GitHub ref
            # endpoints may answer HTTP 409 while no commits exist.
            pushed = self._push_root_commit(
                prepared,
                access_token=access_token,
                remote_url=remote_url,
            )
        else:
            # An earlier ambiguous attempt may have pushed successfully before
            # Nexuss lost the response. Verify that exact approved root commit
            # instead of overwriting or creating a second commit.
            existing_commit = api.get_git_reference(
                prepared.owner_login,
                prepared.repository_name,
                f"heads/{prepared.branch}",
            )
            if existing_commit is None:
                raise ConnectorError(
                    "GITHUB_ARCHIVE_REPOSITORY_NOT_EMPTY",
                    "The repository is not empty and has no approved branch.",
                )
            commit_payload = api.get_git_commit(
                prepared.owner_login,
                prepared.repository_name,
                existing_commit,
            )
            tree_payload = commit_payload.get("tree")
            if not isinstance(tree_payload, dict) or not tree_payload.get("sha"):
                raise ConnectorError(
                    "GITHUB_ARCHIVE_COMMIT_RESPONSE_INVALID",
                    "GitHub returned an invalid existing root commit.",
                )
            pushed = RootCommitPush(
                commit_sha=existing_commit,
                tree_sha=str(tree_payload["sha"]),
                reference_sha=existing_commit,
            )
        last_error: ConnectorError | None = None
        for attempt in range(self._VERIFY_ATTEMPTS):
            try:
                return verifier._verify(
                    api,
                    prepared,
                    approval,
                    repository_was_empty=was_empty,
                    commit_sha=pushed.commit_sha,
                    tree_sha=pushed.tree_sha,
                    reference_sha=pushed.reference_sha,
                    expected_tree=expected_tree,
                    checked_at=datetime.now(UTC),
                )
            except ConnectorError as exc:
                last_error = exc
                if attempt + 1 >= self._VERIFY_ATTEMPTS:
                    break
                time.sleep(self._VERIFY_DELAY_SECONDS)

        assert last_error is not None
        raise last_error

    def _push_root_commit(
        self,
        prepared: PreparedArchivePublish,
        *,
        access_token: str,
        remote_url: str | None = None,
    ) -> RootCommitPush:
        git = shutil.which("git")
        if git is None:
            raise ConnectorError(
                "GITHUB_GIT_RUNTIME_MISSING",
                "Git is required for exact empty-repository publication.",
            )
        if not access_token and remote_url is None:
            raise ConnectorError(
                "GITHUB_TOKEN_MISSING",
                "The GitHub access token is unavailable.",
            )

        source_root = Path(prepared.source_root).resolve()
        destination = remote_url or (
            f"https://github.com/{prepared.owner_login}/"
            f"{prepared.repository_name}.git"
        )

        with tempfile.TemporaryDirectory(
            prefix="nexuss-root-commit-"
        ) as temporary:
            repo = Path(temporary)
            environment = os.environ.copy()
            environment.update(
                {
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_ASKPASS_REQUIRE": "force",
                    "NEXUSS_GITHUB_TOKEN": access_token,
                    "GIT_AUTHOR_NAME": "Nexuss",
                    "GIT_AUTHOR_EMAIL": "noreply@nexuss.local",
                    "GIT_COMMITTER_NAME": "Nexuss",
                    "GIT_COMMITTER_EMAIL": "noreply@nexuss.local",
                }
            )

            askpass = repo / "nexuss-git-askpass.cmd"
            askpass.write_text(
                "@echo off\r\n"
                "echo %~1 | findstr /I \"Username\" >nul\r\n"
                "if %errorlevel%==0 (\r\n"
                "  echo x-access-token\r\n"
                ") else (\r\n"
                "  echo %NEXUSS_GITHUB_TOKEN%\r\n"
                ")\r\n",
                encoding="ascii",
            )
            environment["GIT_ASKPASS"] = str(askpass)

            self._run(
                [git, "init", "--quiet"],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            )
            self._run(
                [git, "config", "core.autocrlf", "false"],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            )
            self._run(
                [git, "config", "core.filemode", "true"],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            )

            for item in prepared.files:
                content = self._read_verified_source(
                    source_root,
                    item,
                )
                blob_sha = self._run(
                    [git, "hash-object", "-w", "--stdin"],
                    cwd=repo,
                    environment=environment,
                    input_bytes=content,
                    access_token=access_token,
                ).strip()
                if blob_sha != item.git_blob_sha1:
                    raise ConnectorError(
                        "GITHUB_ARCHIVE_LOCAL_BLOB_MISMATCH",
                        "The local Git blob differs from the approved blob.",
                        safe_details={"path": item.path},
                    )
                self._run(
                    [
                        git,
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        item.git_mode,
                        blob_sha,
                        item.path,
                    ],
                    cwd=repo,
                    environment=environment,
                    access_token=access_token,
                )

            tree_sha = self._run(
                [git, "write-tree"],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            ).strip()
            commit_sha = self._run(
                [
                    git,
                    "commit-tree",
                    tree_sha,
                    "-m",
                    prepared.commit_message,
                ],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            ).strip()

            self._run(
                [git, "remote", "add", "origin", destination],
                cwd=repo,
                environment=environment,
                access_token=access_token,
            )
            try:
                self._run(
                    [
                        git,
                        "push",
                        "--porcelain",
                        "origin",
                        (
                            f"{commit_sha}:refs/heads/"
                            f"{prepared.branch}"
                        ),
                    ],
                    cwd=repo,
                    environment=environment,
                    access_token=access_token,
                )
            finally:
                environment["NEXUSS_GITHUB_TOKEN"] = ""

        return RootCommitPush(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            reference_sha=commit_sha,
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
                "An approved archive file is missing.",
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

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        access_token: str,
        input_bytes: bytes | None = None,
    ) -> str:
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                input=input_bytes,
                capture_output=True,
                timeout=self._COMMAND_TIMEOUT_SECONDS,
                check=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConnectorError(
                "GITHUB_GIT_COMMAND_UNAVAILABLE",
                "The exact Git publication command could not run.",
                retryable=isinstance(
                    exc,
                    subprocess.TimeoutExpired,
                ),
                safe_details={"command": command[1]},
            ) from exc

        stdout = completed.stdout.decode(
            "utf-8",
            errors="replace",
        ).strip()
        stderr = completed.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()
        if access_token:
            stdout = stdout.replace(access_token, "[REDACTED]")
            stderr = stderr.replace(access_token, "[REDACTED]")

        if completed.returncode != 0:
            raise ConnectorError(
                "GITHUB_GIT_PUSH_FAILED",
                "Git could not publish the approved root commit.",
                retryable=False,
                safe_details={
                    "command": command[1],
                    "exit_code": completed.returncode,
                    "stderr": stderr[-2000:],
                    "stdout": stdout[-1000:],
                },
            )
        return stdout

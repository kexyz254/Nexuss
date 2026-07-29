"""Modification boundary for the read-only P6.6A milestone."""

from __future__ import annotations


class GitHubModificationDisabled(RuntimeError):
    pass


class GitHubChangeManager:
    """Fail closed until the separate phone-approved modification milestone."""

    @staticmethod
    def prepare_change(*_args: object, **_kwargs: object) -> None:
        raise GitHubModificationDisabled(
            "GitHub modification is disabled in P6.6A. "
            "No branch, commit, push, pull request, issue edit, or merge capability is registered."
        )

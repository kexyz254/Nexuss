"""Typed failures for the Nexuss intelligence plane."""

from __future__ import annotations


class IntelligenceError(RuntimeError):
    """A fail-closed intelligence-plane failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

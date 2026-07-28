"""Controlled engineering-plane failures."""

from __future__ import annotations


class EngineeringError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        safe_details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.safe_details = safe_details or {}

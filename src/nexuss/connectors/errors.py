"""Typed connector failures that map cleanly into Nexuss receipts."""

from __future__ import annotations


class ConnectorError(RuntimeError):
    """A controlled connector failure."""

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

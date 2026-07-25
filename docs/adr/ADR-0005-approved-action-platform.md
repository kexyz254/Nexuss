# ADR-0005: Establish the Approved Action Platform

**Status:** Accepted for implementation on `feature/p3-approved-local-actions`

**Copyright:** © kexyz254peter. Confidential and Proprietary.

## Context

P2 proved a live read-only capability and same-origin browser interface. Nexuss now needs a reusable trust pattern for real side effects rather than feature-specific write shortcuts.

## Decision

P3 introduces an explicit capability registry, validated lifecycle state machine, session-bound exact-payload approval, controlled executor, evidence verification, append-only receipt versions, and receipt-bound rollback.

The first real action is `workspace.create_note`. It may write only a UTF-8 Markdown file beneath the Nexuss managed workspace. It cannot accept an arbitrary path, overwrite a file, invoke a shell, create executable content, or execute before approval.

Approval is valid only when its identifier, one-time token, payload SHA-256, authenticated session, pending status, and expiry all match the server-side task. The approval token is removed from returned task state after consumption.

Rollback is permitted only for a completed receipt that created a note. Before deletion, Nexuss recomputes the file SHA-256 and requires an exact match with the creation evidence. Modified or unrelated files are never deleted.

## Consequences

All future write-capable integrations must use the same planning, policy, approval, execution, verification, receipt, and rollback interfaces. Process-local storage is acceptable only for this private prototype and must be replaced before multi-process or production deployment.

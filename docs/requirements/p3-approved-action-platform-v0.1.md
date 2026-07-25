# P3 Approved Action Platform Requirements v0.1

**CONFIDENTIAL - NEXUSS AI - kexyz254peter**

1. Nexuss shall answer identity, capability, and help questions without treating them as prohibited actions.
2. Nexuss shall deny every unregistered capability.
3. Nexuss shall expose capability manifests with risk, status, approval policy, execution mode, and reversibility.
4. Nexuss shall create no managed note before explicit approval.
5. Approval shall be bound to the authenticated session, exact payload SHA-256, one-time token, task, and expiration.
6. Approval payload modification, token reuse, session mismatch, and expiration shall fail closed.
7. Managed note titles shall reject traversal syntax, absolute paths, reserved names, and unsafe destinations.
8. Managed notes shall be limited to Markdown, UTF-8, 32 KiB, no overwrite, and atomic exclusive creation.
9. Post-write evidence shall include filename, managed path, byte count, SHA-256, source mode, and verification state without logging note content.
10. Action Receipts shall be append-only versioned snapshots with complete lifecycle events.
11. Rollback shall delete only the unchanged file owned by the associated creation receipt.
12. The UI shall display lifecycle, policy, approval preview, evidence, receipt, and Undo state.
13. Voice transcripts shall remain reviewable and shall not bypass explicit approval.
14. All P1 and P2 safety boundaries shall remain enforced.
15. Ruff, MyPy strict, Bandit, repository validation, unit, contract, integration, and CI gates shall pass before merge.

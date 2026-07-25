# P3 Approved Actions Threat Model

**CONFIDENTIAL - NEXUSS AI - kexyz254peter**

## Protected assets

- User-controlled managed workspace files
- Approval tokens and session binding
- Exact action payloads
- Action Receipt integrity and rollback ownership
- Nexuss source repository and host filesystem

## Principal threats and controls

- **Path traversal or arbitrary path write:** reject separators, traversal syntax, reserved names, and any resolved target whose parent is not the configured managed root.
- **Overwrite or race:** use exclusive atomic create flags and never enable overwrite in P3.
- **Approval tampering:** SHA-256 bind the capability parameters; compare identifiers, token, hash, session, state, and expiry server-side.
- **Approval replay:** accept pending tokens once and remove them after consumption.
- **Cross-session authorization:** bind task and approval to the authenticated session UUID.
- **Unauthorized rollback:** permit only completed receipt-owned note results and verify the live file hash before deletion.
- **Secret or content leakage:** do not include note content in Action Receipts, capability evidence, or ordinary logs; preview it only in the approval response to the bound browser session.
- **Arbitrary command execution:** managed note operations use direct filesystem APIs only; no shell is invoked.
- **Unknown capability execution:** capability registry lookup fails closed.
- **Process restart:** prototype state loss is explicit; production readiness is denied until encrypted persistence is implemented.

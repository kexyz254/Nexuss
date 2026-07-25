# Nexuss AI OS

> **CONFIDENTIAL - NEXUSS AI - kexyz254peter - Unauthorized distribution prohibited**

Nexuss is a user-owned Personal Cognitive Operating System that converts natural-language intent into secure, policy-governed, verifiable digital action.

## Current stage

Prototype Increment P3: Approved Action Platform.

P3 provides a premium browser control surface at `http://127.0.0.1:8100/` where a user can type or dictate an instruction, inspect the plan and policy decision, approve exact write payloads, view verified evidence, inspect append-only Action Receipt versions, and undo an eligible receipt-owned action.

### Live capabilities

- `workspace.read_status`: bounded, live, local, read-only repository and runtime metadata.
- `workspace.create_note`: real Markdown note creation inside the Nexuss managed workspace after exact-payload approval.
- `workspace.rollback_create_note`: receipt-bound removal of only an unchanged note created by Nexuss.
- `assistant.respond`: deterministic identity, capability, and help responses without side effects.

### Simulated capabilities

Calendar, email, GitHub summary, and ATS intelligence remain explicitly simulated. The UI and receipts never present simulation as live data.

## Approved-action security boundary

P3 enforces:

- explicit capability registration;
- fail-closed policy evaluation;
- authenticated session binding;
- one-time, five-minute approval tokens;
- SHA-256 binding to the exact action payload;
- managed-directory confinement;
- path-traversal and reserved-name rejection;
- Markdown-only, UTF-8, 32 KiB notes;
- atomic exclusive creation with no overwrite;
- post-write SHA-256 verification;
- append-only receipt versions;
- hash-verified, receipt-owned rollback;
- no shell execution and no arbitrary filesystem access.

The default managed workspace is:

```text
~/.nexuss/workspace
```

It can be changed for a private development environment using `NEXUSS_MANAGED_WORKSPACE` before the server starts.

## Current prohibitions

This repository does **not** authorize:

- real-money transfers;
- autonomous trading or betting;
- production ATS modification;
- arbitrary command execution;
- unrestricted file access or deletion;
- unattended social publishing;
- credential recovery;
- undisclosed voice impersonation.

## Run locally

```bash
python scripts/validate_repository.py
python -m pytest tests
uvicorn nexuss.api.app:app --host 127.0.0.1 --port 8100 --reload
```

Then open:

```text
http://127.0.0.1:8100/
```

Recommended P3 demonstration:

```text
Create a note called Nexuss launch checklist with the tasks: verify P3, review the Action Receipt, and test undo.
```

Browser speech recognition is a progressive enhancement. The transcript is shown for review before execution, and voice never bypasses approval.

## Engineering principles

- contract-first interfaces;
- zero implicit trust;
- explicit capability manifests;
- read-only-first integrations;
- approval for consequential actions;
- verifiable results before completion;
- append-only Action Receipts;
- reversible actions where technically safe;
- reproducible builds;
- no secrets in source control.

## Prototype limitation

P3 task, approval, and receipt state is process-local. Restarting Uvicorn clears that prototype state. Encrypted durable persistence and multi-process coordination are required before production deployment.

## Ownership

Copyright © kexyz254peter. All rights reserved.

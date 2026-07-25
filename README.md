# Nexuss AI OS

> **CONFIDENTIAL - NEXUSS AI - kexyz254peter - Unauthorized distribution prohibited**

Nexuss is a user-owned Personal Cognitive Operating System that converts natural-language intent into secure, policy-governed, cross-device action.

## Current stage

Prototype Increment P2: browser control surface plus the first live, local, read-only capability.

P2 provides an end-to-end interface at `http://127.0.0.1:8100/` where a user can type or dictate an instruction, inspect the deterministic plan and policy decisions, view execution evidence, and verify the Action Receipt.

The first live capability, `workspace.read_status`, collects bounded local metadata only:

- operating-system and Python runtime identity;
- current Nexuss repository, Git branch, commit, and clean/modified state;
- available disk capacity;
- evidence timestamp and explicit `live_local_readonly` source mode.

It does not read user file contents, expose credentials, execute arbitrary shell commands, modify the workspace, or connect to production ATS execution.

## Current safety boundaries

This repository does **not** authorize:

- real-money transfers;
- autonomous trading or betting;
- undisclosed voice impersonation;
- unattended social publishing;
- credential recovery;
- production ATS modification;
- arbitrary command execution.

## Architecture rule

ATS is one protected specialist subsystem connected through a read-only contract. Nexuss remains the parent interaction, policy, orchestration, device, and data-control layer.

## Run locally

```bash
python scripts/validate_repository.py
python -m pytest tests
uvicorn nexuss.api.app:app --host 127.0.0.1 --port 8100
```

Then open:

```text
http://127.0.0.1:8100/
```

Browser speech recognition is a progressive enhancement. The transcript is shown for review before execution; text input remains available when browser voice support is unavailable.

## Repository principles

- contract-first interfaces;
- zero implicit trust;
- read-only-first integrations;
- fail-closed consequential actions;
- verifiable results before completion;
- complete Action Receipts;
- reproducible builds;
- no secrets in source control.

## Ownership

Copyright © kexyz254peter. All rights reserved.

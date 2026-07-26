# Nexuss AI OS

> **CONFIDENTIAL - NEXUSS AI - kexyz254peter - Unauthorized distribution prohibited**

Nexuss is a user-owned Personal Cognitive Operating System that converts natural-language intent into secure, policy-governed, verifiable digital action.

## Current stage

Prototype Increment P4: Trusted Device Mesh and Phone Approval.

P4 extends the premium browser control surface with the first real trusted-device command. A user can type or dictate “Open Notepad on this computer,” inspect the deterministic plan and exact payload, pair a phone on the same private network, approve the command from that phone, watch the Windows node execute the allowlisted command, inspect verified process evidence, and reverse only the receipt-bound process.

### Live capabilities

- `workspace.read_status`: bounded, live, local, read-only repository and runtime metadata.
- `workspace.create_note`: real Markdown note creation inside the Nexuss managed workspace after exact-payload desktop approval.
- `workspace.rollback_create_note`: receipt-bound removal of only an unchanged note created by Nexuss.
- `device.launch_notepad`: real launch of the fixed Windows Notepad executable after paired-phone approval.
- `device.rollback_launch_notepad`: receipt-bound termination of only the process created by the trusted node.
- `assistant.respond`: deterministic identity, capability, and help responses without side effects.

### Simulated capabilities

Calendar, email, GitHub summary, and ATS intelligence remain explicitly simulated. The UI and receipts never present simulation as live data.

## P4 device-trust boundary

P4 enforces:

- explicit capability registration and fail-closed policy evaluation;
- phone-only approval for trusted-device commands;
- single-use eight-digit pairing codes bound to the desktop session;
- high-entropy phone bearer sessions with eight-hour expiry;
- exact approval ID, one-time token, and SHA-256 payload matching;
- a separately running Windows node bound to loopback only;
- HMAC-SHA256 signed, 30-second command envelopes;
- nonce replay protection and exact target-node validation;
- one fixed absolute executable path with no shell and no arguments;
- verified node, hostname, executable, process, and running-state evidence;
- append-only Action Receipts;
- receipt-bound process rollback;
- private-network startup checks;
- loopback-only desktop control and task APIs;
- per-client pairing rate limits;
- loopback-only device-client URL enforcement with ambient proxies disabled;
- no automatic firewall changes and no internet relay.

## Start P4 on Windows

First stop any earlier Nexuss process using ports 8100 or 8200. Then run:

```powershell
Set-Location C:\NexussWorkspace\Nexuss-P0
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_p4.ps1
```

The script starts:

- Nexuss Core and desktop UI on `0.0.0.0:8100` so the phone can reach the approval page on the private LAN;
- the trusted Windows node on `127.0.0.1:8200` only;
- an ephemeral shared secret inherited through child-process environment variables and omitted from command-line arguments.

The console prints the desktop and phone URLs. If Windows Firewall prompts, allow access only on **Private networks**.

Recommended P4 demonstration:

```text
Open Notepad on this computer.
```

The desktop must remain in `awaiting_approval` until the paired phone approves the exact command. After execution, use **Undo action** to close only the receipt-bound Notepad process.

## Existing P3 managed workspace

The default managed-note workspace remains:

```text
~/.nexuss/workspace
```

It can be changed for a private development environment using `NEXUSS_MANAGED_WORKSPACE` before startup.

## Current prohibitions

This repository does **not** authorize:

- arbitrary command or shell execution;
- user-controlled executables, arguments, scripts, or system paths;
- public-internet exposure of the phone approval endpoint;
- real-money transfers;
- autonomous trading or betting;
- production ATS modification;
- unrestricted file access or deletion;
- unattended social publishing;
- credential recovery;
- undisclosed voice impersonation.

## Engineering principles

- contract-first interfaces;
- zero implicit trust;
- explicit capability manifests;
- read-only-first integrations;
- independent approval for consequential actions;
- signed and expiring execution envelopes;
- verifiable results before completion;
- append-only Action Receipts;
- reversible actions where technically safe;
- reproducible builds;
- no secrets in source control.

## Prototype limitation

P4 phone pairing, task, approval, nonce, process, and receipt state is process-local. The mobile approval page must remain open or active to poll for requests; P4 does not yet provide an operating-system push notification. The phone client uses a private-LAN browser bearer session and must not be exposed to the public internet. Native Android hardware-backed identity, mutual TLS, encrypted durable persistence, secure push notifications, and remote revocation are required before production deployment.

## Ownership

Copyright © kexyz254peter. All rights reserved.

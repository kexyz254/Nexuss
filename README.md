# Nexuss AI OS

> **CONFIDENTIAL — NEXUSS AI — kexyz254peter — Unauthorized distribution prohibited**

Nexuss is a user-owned Personal Cognitive Operating System that converts natural-language intent into policy-governed, verifiable digital action.

## Current stage

Prototype Increment P5.1: Intent-Aware YouTube Workspace and Direct Paired-Phone Handoffs.

P5.1 extends the verified P5 media plane with:

- context-aware media intent normalization and structured title/artist extraction;
- official YouTube search plus public video-detail enrichment and deterministic ranking;
- a rich result catalog, queue, theater mode, and native browser fullscreen;
- direct desktop YouTube navigation and direct allowlisted handoff to an already paired phone;
- approval retained for higher-risk browser, device, write, and destructive capabilities.

### P5.1 capabilities

- `media.youtube.discover`: retrieve and rank embeddable public videos using the official YouTube Data API;
- `phone.open_youtube`: queue an exact allowlisted YouTube search to a paired phone without an additional approval prompt;
- contextual media controls: pause, resume, previous, next, mute, unmute, minimize, maximize, fullscreen, close, and result selection;
- rich result cards: thumbnail, title, channel, description, duration, publication date, view count, and match evidence;
- `knowledge.web_research`: retain the bounded public-research plane as a separate provider capability;
- `device.open_web_search`: retain phone approval for general Chrome or Google searches.

P1–P4 capabilities remain available, including local workspace intelligence, managed notes, phone-approved Notepad launch, Action Receipts, and receipt-bound rollback.

## Trust boundary

P5.1 enforces:

- external webpage text is untrusted evidence, never executable instruction;
- provider credentials remain server-side and are excluded from Git, browser storage, logs, and receipts;
- public research is bounded, read-only, time-limited, and source-labelled;
- no automatic promotion of research into long-term memory;
- YouTube search uses the official Data API when configured;
- playback uses the official YouTube IFrame Player API;
- YouTube phone handoffs and outbound links accept HTTPS URLs only from an explicit YouTube hostname allowlist;
- Chrome execution uses a fixed executable and fixed `--new-tab` argument shape with no shell;
- higher-risk phone and device actions retain exact-payload approval; the paired-phone YouTube handoff is the only no-approval mobile exception in P5.1;
- the device node remains loopback-only and signed envelopes remain expiring and replay-protected;
- no arbitrary app, URL, script, executable, intent component, or shell command is accepted.

## Configure official YouTube discovery

Create a restricted API key for the YouTube Data API and provide it only to the current private runtime environment:

```powershell
$env:NEXUSS_YOUTUBE_API_KEY = "<private-runtime-key>"
```

Do not place the key in `.env.example`, source files, screenshots, receipts, or Git. Without the key, Nexuss reports `YOUTUBE_API_KEY_NOT_CONFIGURED` and offers approved phone or Chrome search handoffs. A direct user-supplied YouTube video URL can still be loaded without search.

## Start P5 on Windows

```powershell
Set-Location C:\NexussWorkspace\Nexuss-P0
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start_p5.ps1
```

The script starts:

- Nexuss Core and the desktop/mobile UI on private-LAN port `8100`;
- the trusted Windows node on loopback port `8200`;
- a process-local cryptographic device secret inherited by child processes and omitted from command-line arguments.

If Windows Firewall prompts, allow access only on **Private networks**. Never port-forward or publicly expose port `8100`.

Recommended P5.1 demonstrations:

```text
Research the fundamentals of forex and prepare a cited beginner brief.
Play Silence by Popcaan.
Open YouTube on my phone and search Silence by Popcaan.
Open Chrome and search forex risk management.
```

## Honest YouTube and mobile limitations

P5.1 provides public YouTube search, public metadata, an official embedded player, a local queue, and outbound YouTube links. It does not reproduce personalized home recommendations, subscriptions, comments, account history, likes, or uploads. Those features require a separately reviewed OAuth connector and narrowly scoped user consent.

The paired private-LAN mobile web client can claim a YouTube-only handoff without an additional approval prompt. Android may route that URL to the installed YouTube app, but Nexuss records `app_open_verified: false` because a signed native Android companion node is not yet present. Hardware-backed enrollment, push delivery, native app attestation, and MediaSession control remain later increments.

## Existing managed workspace

The default managed-note workspace is:

```text
~/.nexuss/workspace
```

It can be changed in a private development environment through `NEXUSS_MANAGED_WORKSPACE` before startup.

## Current prohibitions

This repository does **not** authorize:

- arbitrary browsing, URL opening, command, shell, script, or executable execution;
- webpage-driven tool calls or prompt-injection instructions;
- scraping or downloading YouTube media;
- public-internet exposure of the phone approval surface;
- unrestricted Android UI automation or AccessibilityService control;
- real-money transfers, autonomous trading, or ATS writes;
- unrestricted file access, deletion, or unattended publishing;
- credential recovery or undisclosed voice impersonation.

## Engineering principles

- contract-first interfaces;
- fail-closed capability registry;
- least privilege and explicit approval;
- deterministic plans before side effects;
- verified evidence before completion;
- append-only Action Receipts;
- reversible actions where technically safe;
- private-branch review and green CI before merge;
- no secrets in source control;
- all proprietary artifacts marked for `kexyz254peter`.

## Ownership

Copyright © kexyz254peter. All rights reserved.

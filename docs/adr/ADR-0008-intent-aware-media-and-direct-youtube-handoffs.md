# ADR-0008: Intent-Aware Media and Direct YouTube Handoffs

> **CONFIDENTIAL — NEXUSS AI — kexyz254peter — Unauthorized distribution prohibited**

- **Status:** Proposed for P5.1 review
- **Decision owner:** kexyz254peter

## Context

The P5 media plane proved official YouTube discovery and embedded playback, but its first-pass parser was too literal, its result surface exposed too little discovery context, and a YouTube-only phone handoff inherited an approval requirement designed for higher-risk device actions.

## Decision

Nexuss will introduce a deterministic intent-normalization layer for bounded media commands, structured title and artist extraction, two-stage YouTube discovery using `search.list` followed by `videos.list`, and evidence-based ranking. The UI will present a provider-style catalog workspace with rich public metadata, explicit result selection when confidence is ambiguous, official embedded playback, theater mode, and browser fullscreen.

Desktop YouTube navigation initiated by the user and a YouTube-only handoff to an already paired phone will use `ApprovalPolicy.NONE`. The relaxation is capability-specific, not global. The phone remains authenticated, the destination remains HTTPS and YouTube-only, each handoff is claimed once, and Nexuss records that native app opening is not verified.

General Chrome searches, arbitrary URLs, Windows-node commands, writes, publishing, financial actions, and destructive operations retain their existing approval or prohibition policies.

## Consequences

- Users can express ordinary media intent without memorizing a rigid command grammar.
- Ambiguous searches remain reviewable rather than silently autoplaying a weak match.
- The media workspace is substantially closer to a normal YouTube discovery experience while retaining official provider playback and links.
- Personalized YouTube account features remain unavailable until a separate OAuth-scoped connector is reviewed.
- The paired-phone web client must remain active to receive a prototype handoff; cryptographic native execution attestation remains deferred.

Copyright © kexyz254peter. All rights reserved.

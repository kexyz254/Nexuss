# ADR-0003: Deterministic P1 Core Simulator

**Status:** Accepted for implementation on `feature/p1-core-simulator`
**Classification:** CONFIDENTIAL - NEXUSS AI - kexyz254peter

## Context

Nexuss needs a complete request-to-receipt lifecycle before connecting real devices,
accounts, credentials, or specialist systems. An external language model would make
initial behavior harder to reproduce and audit.

## Decision

P1 uses a deterministic rules-based intent classifier, deterministic UUIDv5 plan IDs,
a fail-closed policy engine, simulated capability results explicitly marked as simulated,
and an in-memory append-only Action Receipt ledger.

The root Python project adopts a `src/` package layout. Real connectors and persistent
storage remain excluded.

## Consequences

- CI and tests can reproduce every lifecycle decision.
- No simulated result may be presented as real-world data.
- Unknown and prohibited capabilities are denied before execution.
- Later cognition models must preserve the same typed contracts and policy boundary.

# ADR-0004: Build UI and live local read-only capability as one vertical slice

**Status:** Accepted for implementation on `feature/p2-local-readonly-capability`

## Context

Terminal-only demonstrations validate the API but do not validate the intended Nexuss interaction model. The project requires an interface through which the user can type or speak an intention and inspect the complete request, policy, execution, evidence, and receipt lifecycle while capabilities are developed.

## Decision

P2 introduces a same-origin browser control surface served directly by the FastAPI application. It supports text input and progressive browser speech recognition. Voice produces a reviewable transcript; Nexuss does not execute an interim transcript automatically.

P2 also replaces one simulated pathway with `workspace.read_status`, a live local read-only capability. The provider uses Python standard-library metadata functions and fixed, no-shell Git commands. The repository root is derived from the installed Nexuss source, not accepted from the user request.

## Security constraints

- No arbitrary command or path supplied by the UI reaches the provider.
- Git calls are fixed, bounded, no-shell, and time limited.
- No user file contents are read.
- No credentials, environment-variable values, process lists, or network configuration are returned.
- Evidence is labelled `live_local_readonly`.
- All execution remains subject to the policy engine and Action Receipt.

## Consequences

The UI becomes the primary development verification surface. New capabilities must expose policy and evidence in the same interface. Browser voice support varies, so text remains the authoritative fallback until a dedicated speech service is approved.

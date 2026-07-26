# ADR-0006: Trusted Device Mesh and Phone Approval

**Status:** Accepted for implementation on `feature/p4-trusted-device-mesh`

Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

## Context

P3 proved exact-payload desktop approval for bounded local writes. Device control introduces a broader trust boundary: a command may affect a separate operating-system process and must not be approved solely from the same interface that requested it.

## Decision

P4 introduces a separately running Windows device node and a phone-approval client. Nexuss Core creates a deterministic `device.launch_notepad` plan, classifies it as high risk, and pauses before execution. The desktop approval endpoint cannot approve the command. A paired phone must approve the same approval ID, one-time token, and SHA-256 payload fingerprint.

Core sends a short-lived HMAC-SHA256 signed envelope to a loopback-only device node. Desktop control APIs remain loopback-only even though the mobile approval surface is reachable on the private LAN. The node rejects expired, replayed, unsigned, unregistered, or wrong-target envelopes. The only P4 command is the fixed absolute Windows Notepad executable with no shell and no user-controlled arguments.

## Consequences

The implementation proves cross-interface approval and real device execution while preserving a narrow capability boundary. The private-LAN phone client is a laboratory surface, not a production security boundary. Native Android certificate-backed identity, mutual TLS, encrypted durable state, revocation, and secure push delivery remain mandatory before production deployment.

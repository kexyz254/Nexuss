# P4 Device Mesh Threat Model

Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

## Protected assets

- User intent and approval decisions
- Device-node shared secret
- Phone pairing and session tokens
- Command and rollback identities
- Capability registry integrity
- Action Receipts and execution evidence

## Principal threats and controls

| Threat | P4 control |
|---|---|
| Arbitrary shell execution | No shell API; single fixed executable and no arguments |
| Desktop bypasses phone approval | Approval channel is contract-bound; desktop approval returns `PHONE_APPROVAL_REQUIRED` |
| Payload changed after approval | Approval ID, token, and SHA-256 must all match |
| Core-to-node tampering | HMAC-SHA256 canonical envelope signature; client URL is constrained to loopback and ignores ambient proxies |
| Replay of a device command | Random nonce cache and 30-second expiry |
| Command targets wrong node | Exact `target_node_id` validation |
| Rollback kills unrelated process | Command ID, task ID, node ID, and process handle are receipt-bound |
| Pairing-code guessing | Eight-digit random code, ten-minute expiry, single use, private LAN only, and per-client rate limiting |
| Stolen phone bearer token | Eight-hour expiry and process-local revocation; native keystore is deferred |
| Private-LAN lateral access | Desktop/task/receipt/pairing-challenge endpoints are loopback-only; LAN clients can reach only the phone surface and authenticated phone APIs |
| Public-network exposure | Startup script requires an active Windows Private profile and prints an explicit warning |
| Internet exposure | No relay, port-forwarding, or firewall automation in P4 |

## Residual risk

The P4 phone client uses plaintext HTTP on a private-LAN browser session and stores a bearer token in browser local storage. It is sufficient for a controlled local prototype but not for production. P5 production trust work must replace it with a native Android companion using hardware-backed keys, mutually authenticated TLS, encrypted persistent identity, secure push delivery, device attestation, and remote revocation.

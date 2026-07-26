# Nexuss P4 Trusted Windows Device Node

Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

The P4 Windows node is a separately running, loopback-only FastAPI service. It does not expose a shell. It accepts only signed, short-lived command envelopes from Nexuss Core and currently allowlists one demonstration capability: `device.launch_notepad`.

## Security boundary

- Node listens only on `127.0.0.1:8200`.
- Core-to-node requests use HMAC-SHA256 signatures with an ephemeral startup secret.
- Envelopes expire after 30 seconds.
- Nonces are replay-protected.
- The executable is the fixed absolute Windows Notepad path.
- Shell invocation and user-controlled executable paths are prohibited.
- Evidence records node identity, process ID, executable, timestamp, and verified running state.
- Rollback can terminate only the process bound to the original command receipt.

Use `scripts/start_p4.ps1` to start the node and core together. The phone approval surface is exposed only on the local private network. This is a confidential laboratory implementation, not an internet-facing production deployment. Native Android certificate-backed enrollment and mutual TLS remain required before production release.

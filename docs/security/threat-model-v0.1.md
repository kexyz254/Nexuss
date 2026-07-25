# Nexuss Threat Model v0.1

**CONFIDENTIAL - kexyz254peter**

## Initial protected assets

- user identity and sessions;
- device credentials;
- connector tokens;
- personal context;
- Action Ledger;
- ATS gateway data and research boundary;
- release artifacts.

## Initial threat categories

1. Spoofed user or device identity.
2. Replayed or modified capability calls.
3. Malicious connector/provider response.
4. Secret leakage through logs or model context.
5. Prompt injection from email, webpages, or external data.
6. Unauthorized ATS access or strategy disclosure.
7. False success reporting.
8. Dependency or build-chain compromise.
9. Excessive monitoring or privacy overreach.
10. Lost device with active credentials.

## P0 controls

- typed contracts;
- no production secrets;
- read-only connectors;
- explicit device enrollment design;
- fail-closed policy tests;
- secret scanning;
- dependency review;
- complete task correlation and evidence requirements.

# P1 Core Simulator Requirements v0.1

**CONFIDENTIAL - NEXUSS AI - kexyz254peter**

| ID | Requirement | Verification |
|---|---|---|
| NXS-P1-FR-001 | Accept a typed task request with a matching authenticated session. | API and service tests |
| NXS-P1-FR-002 | Classify supported intents deterministically. | Unit tests |
| NXS-P1-FR-003 | Build an ordered, typed and deterministic task plan. | Unit tests |
| NXS-P1-FR-004 | Evaluate every step before any execution. | Policy and lifecycle tests |
| NXS-P1-FR-005 | Deny ATS writes, financial transfers, social publishing and unknown capabilities. | Negative tests |
| NXS-P1-FR-006 | Require approval for simulated workspace preparation. | Lifecycle test |
| NXS-P1-FR-007 | Execute only explicitly allowed simulated capabilities. | Unit and integration tests |
| NXS-P1-FR-008 | Generate one immutable Action Receipt for every accepted request. | Ledger tests |
| NXS-P1-FR-009 | Treat duplicate request IDs idempotently. | Integration test |
| NXS-P1-NFR-001 | Never label simulated evidence as real data. | Contract and content tests |
| NXS-P1-NFR-002 | Preserve full typing, lint, security and CI gates. | GitHub Actions |

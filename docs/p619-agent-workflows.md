# P6.19: specialist roles and bounded TAS engineering

This increment implements a twelve-role catalogue, durable TAS investigations,
structured breaker incident evidence, and a bounded candidate-preparation path.
It is not twelve autonomous deployed agents or full TAS administration.

## Chat entry points

- `List Nexuss agents`
- `Investigate why TAS's circuit breaker is tripped`
- `Resume TAS investigation <run UUID>`
- `Prepare TAS repair <run UUID>`
- `Review TAS repair <run UUID>`
- `Investigate TAS and prepare a tested repair if a defect is found`

Both legacy chat and the unified desktop/mobile chat route use the same workflow.
Natural cause questions such as `Why is TAS's breaker tripped?` start an
investigation. `Continue the investigation`, `try again`, and `prepare a repair`
resolve the latest run in the same authenticated conversation. Other TAS phrasing
can use the configured AI provider to select a strictly allowlisted read intent;
this requires the existing external-processing consent. The language planner
cannot create shell, trade, restart, reset or deployment actions.

Blocked reads distinguish connection errors, timeouts, authentication rejection,
missing endpoints and unavailable upstream TAS evidence without copying raw
exceptions. Partial evidence yields a partial risk assessment, not an implied
completed diagnosis. Repair preparation requires completed health, incident and
source steps, and health/incident capture times within five minutes. Restart is
distinct from clearing the breaker; neither has an execution adapter here.

Investigations are scoped to the authenticated user session and conversation.
SQLite receipts live under `%LOCALAPPDATA%/Nexuss/workflows/tas.sqlite3` on Windows.
Resume retains successful evidence and retries missing/failed reads. Start a new
investigation for fresh evidence. Receipt hashes detect accidental payload changes;
they are not signatures protecting against a compromised local machine.

## Roles and actual execution

Research collects typed incident evidence; Maintenance reads health; Engineering
reads a pinned source snapshot and can prepare a candidate; Data normalizes those
results; Risk records breaker/freshness/deployment uncertainties; Security records
boundary checks and performs a separate model review of proposed changes;
Validation runs the targeted baseline/regression/candidate checks.
Market retains the existing recorded-decision reader. Learning currently retains
receipts, not autonomous self-improvement. Financial, Internet and Social are
declared responsibilities without new live integrations in this increment.
Existing general Nexuss capabilities are not reassigned or bypassed.

## Repair scope and prerequisites

The only proposed implementation replacement is
`trading_assistant/agents/circuit_breaker.py`, accompanied by
`tests/test_nexuss_repair_regression.py`. There is no generic shell command from
the model. A trip by itself is not a defect. The incident endpoint reports a
structured trigger, not necessarily the underlying cause of an execution error.

Preparation requires Nexuss's configured provider, its existing explicit external
processing consent, GitHub snapshot access, Docker on the Nexuss host, and
`NEXUSS_TAS_TEST_IMAGE` set to a preinstalled immutable image ID or digest.
Provider inputs contain two selected source files and typed evidence. Known
credential-shaped content is rejected; this pattern filter is not a complete
secret scanner. No live environment/configuration files are sent to the provider.

The Security/Risk review is a separate pass of the same configured model, not an
independent model or a security certification. Candidate output is never applied
to the deployment. It is copied into a disposable test workspace only.

Tests run with no network, read-only source mount/root filesystem, non-root UID,
no capabilities, bounded CPU/memory/PIDs, and temporary writable storage.
The image's entrypoint is overridden with a fixed pytest command. The host does
not execute candidate Python. The sequence must be:

1. Existing breaker tests pass on the original source.
2. The new regression returns pytest failure code 1 on that original source.
3. Existing tests and the regression pass on the replacement.

This is targeted validation, not full system validation or proof of profitability.
Only output hashes and exit codes are retained; raw test output is not displayed.
The candidate content and review receipt can be inspected in chat. A failed
preparation after candidate creation currently requires a new investigation for
a new candidate attempt. No deployment, restart, reset or trade action is enabled.

## Upgrade

On the VPS, update only the separate bridge worktree to
`origin/feature/p619-agent-workflows`, then rebuild the existing
`nexuss-supervisor` compose project. Its new signed resource is
`/agent/v1/evidence/incident`; it projects the latest breaker event from the
existing `/api/journal` route without returning raw reason strings, trades,
balances or arbitrary journal fields. An older bridge yields a blocked incident
step rather than an invented diagnosis.

On Windows, fast-forward Nexuss to `origin/feature/p619-agent-workflows`, then
restart using the usual stop/start scripts. Existing bridge credentials and
connection settings are retained. Investigation and role-listing do not need
Docker or a paid AI call.

For candidate testing, install/configure Docker separately if unavailable. Build
the dedicated test image from a clean TAS checkout containing
`services/nexuss_bridge/Dockerfile.tests`:

```powershell
docker build -f services/nexuss_bridge/Dockerfile.tests -t nexuss-tas-tests .
if ($LASTEXITCODE -ne 0) { throw "Test image build failed" }
$env:NEXUSS_TAS_TEST_IMAGE = docker image inspect nexuss-tas-tests --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw "Test image lookup failed" }
```

Run Nexuss's stop/start scripts from the same PowerShell session to inherit that
setting. Building the image downloads dependencies; validation itself has no
network. The Dockerfile contains requirements only, not the repo, secrets, or
runtime data. Pinning the resulting image ID makes subsequent validation select
that exact local image. No image is pulled automatically by the validator.

## Verification limits

Focused tests cover bridge redaction, signed incident reads, scoped persistence,
resume after restart, rejected proposals, test gating and chat routing.
Provider and Docker orchestration tests use fakes. Docker execution, Windows
DPAPI/provider access, the test-image build and live deployment require host
verification. The repository-wide Linux test bootstrap requires Windows DPAPI;
focused tests intentionally run with their own conftest boundary.

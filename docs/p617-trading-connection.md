# P6.17 connection milestone

This adds local-control API access to the companion TAS supervisory gateway.
It is not yet wired into the capability broker, chat, dashboard or autonomous
planning. Do not advertise full trading-agent management as available.

Configure NEXUSS_TAS_BRIDGE_URL and NEXUSS_TAS_SECRET_FILE before starting Nexuss.
The secret must match the gateway's private file and must not enter chat, Git or
browser storage. Use HTTPS, a controlled private Tailscale address, or a local
SSH tunnel. The gateway defaults to loopback-only. The client rejects public HTTP
origins, embedded credentials, redirects and oversized responses.

- GET /v1/trading/evidence/health
- GET /v1/trading/evidence/status
- GET /v1/trading/evidence/decisions?symbol=BTC%2FUSDT
- POST /v1/trading/feedback
- GET /v1/trading/worker/status
- GET /v1/trading/observations?after=0&limit=100

The VPS observer persists health transitions and hourly checkpoints while Nexuss
is offline. Read pages using next_cursor, persisting the cursor after processing.
This API enables replay but does not yet run an automatic replay consumer. Check
last_checked for worker staleness and backlog_full for exhausted storage capacity.

These require the existing local-control boundary. Feedback follows the TAS
gateway schema and is advisory only; duplicate IDs cannot replace evidence.
No raw endpoint forwarding, trading, strategy changes, shell, deploy or breaker
reset is supported. HTTP 200 is never interpreted as proof of healthy trading.

Companion implementation: trading-analysis-platform branch
feature/p617-supervisory-gateway, services/nexuss_bridge/README.md.
Its compose service runs separately without restarting the existing engine.

Validation: signed-request unit tests and an in-process client/gateway health
round trip with synthetic TAS data. No live deployment or exchange tests run.
Next milestones: durable event delivery, approved research providers, chat and
capability integration, outcome evaluation and governed repair execution.

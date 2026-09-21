# P6.18 — TAS evidence in Nexuss chat

The unified interactions endpoint and legacy conversation endpoint both recognize
TAS/ATS requests. Existing local-control/session checks run before bridge access.
Results are persisted in the conversation; the unified endpoint keeps its existing
request-id retry behavior. No provider connection or paid model is required for
these reads. Replies are attributed to nexuss-tas/verified-evidence-v1.

Try:
- Check TAS health.
- Show TAS decisions for BTC/USDT.
- Show TAS offline observations.
- Inspect TAS code.

Health replies report actual values and observation time. They never equate HTTP
success with a healthy engine or claim to know the breaker cause. Observation
replies show the first stored page and flag stale worker timestamps. They are not
a background replay consumer. Unknown upstream text is not rendered as instructions.

Source inspection uses Nexuss's existing GitHub workspace connector to take and
analyze a snapshot of kexyz254/trading-analysis-platform at integration/nexuss-p617
(override NEXUSS_TAS_SOURCE_REF if needed). It reports a resolved commit and counts,
retains inspection receipts, and executes no repository code. Nexuss must have its
own GitHub connection configured; ChatGPT's GitHub app does not configure that.
Committed source does not include the VPS's uncommitted deployment configuration.
Raw source and arbitrary logs are not sent to a model or chat in this increment.

## Configure once on Windows

Run scripts/configure_tas.ps1 with the existing private key path. It writes only
the URL and key path to %LOCALAPPDATA%/Nexuss/bridge/connection.json. The client loads
this across restarts. Environment variables still override the saved descriptor.
Restart Nexuss after upgrading. The existing loopback URL still requires the SSH
tunnel; saving settings does not make the tunnel permanent.

For a tunnel-free deployment, both machines must already be connected to your
private network and the gateway must explicitly listen on its Tailscale IP with
appropriate network ACLs. A client setting alone does not publish a server listener.
Do not expose the Nexuss core port 8100 or bind the gateway to 0.0.0.0.

## Not yet implemented

TAS edits, isolated patch generation, tests against an actual TAS candidate,
deployment/rollback approval binding, a self-healing executor, live research,
and outcome evaluation still require subsequent work. Requests to fix/upgrade or
trade are answered honestly without creating a fake approval or falling through
to Nexuss self-modification. This increment does not remove authentication or
turn system ownership into unrestricted remote execution.

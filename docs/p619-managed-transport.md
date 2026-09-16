# Nexuss-owned TAS transport

Nexuss can supervise the SSH forward inside its core process. A separate bridge
terminal is no longer needed **after key authentication is configured**. This
does not move the remote bridge into Windows, install a Windows service, or keep
Nexuss running while the PC is off. The VPS offline observer remains independent.

## One-time configuration

1. Have an existing SSH identity authorized on the VPS for port forwarding, and
   a server host key already verified in the Windows user's OpenSSH known-hosts
   file. Prefer a dedicated forwarding-only account/key. An encrypted identity
   needs its corresponding key loaded in the user's SSH agent; Nexuss never
   collects a password or passphrase. This script does not provision server users
   or authorize keys.
2. In the usual Nexuss PowerShell, configure the existing identity path:

   ```powershell
   .\scripts\configure_tas_tunnel.ps1 -IdentityFile "$HOME\.ssh\id_ed25519"
   .\scripts\configure_tas.ps1 -BridgeUrl "http://127.0.0.1:8300"
   .\scripts\stop_p5.ps1
   .\scripts\start_p5.ps1
   ```

   Use the actual identity filename and `-SshUser` if using a dedicated account.
   The defaults target the previously supplied VPS IP and root account; they do
   not grant root access or copy a private key. Only the file path is saved in
   `%LOCALAPPDATA%/Nexuss/bridge/tunnel.json`. If no identity is authorized yet,
   complete SSH key setup before enabling the background transport.
3. Close the old manual tunnel window and ask `show TAS connection status`, then
   `check TAS health`. If an old tunnel still owns port 8300, Nexuss reports
   `external_listener` and leaves it untouched. Once it closes, the supervisor
   attempts its own connection.

`forwarding` means the managed SSH process is alive and port 8300 is listening.
It does not mean the remote bridge authenticated or that TAS is healthy; only the
signed health read checks that path. `retry_wait` means SSH exited: check key
authentication, previously verified host identity, network and forwarding policy.
`configuration_invalid` and `ssh_unavailable` need local setup corrections.

## Lifecycle and limits

- Startup is opt-in and tied to the Nexuss API's startup/shutdown lifecycle.
- SSH uses no remote command, a fixed loopback-to-loopback forward, noninteractive
  authentication, strict host checking, keepalives, and no inherited SSH config.
- The hidden Windows subprocess is owned by the core. Normal shutdown stops it;
  the existing stop script kills the core process tree. No arbitrary PID is killed.
- Failed exits retry with bounded backoff. Status omits raw SSH output and paths.
- The supervisor does not change keys, host trust, accounts or server SSH policy.
- Closing the **Nexuss core** still stops supervision. There is no promise of
  reconnecting while Windows is shut down or while the core has been force-killed.
- Use the already provided Tailscale listener instead if you want a private
  service-to-service connection without an SSH forward. Do not enable both
  transports for the same local listener.

The transport command follows the [OpenSSH client options](https://man.openbsd.org/ssh.1).
Supervisor tests use fake subprocesses; Windows OpenSSH/agent integration and
the actual VPS connection have not been verified in this development environment.

## Engineering recovery milestone

`Restore TAS health` starts evidence collection and bounded repair preparation;
it does not declare recovery or authorize a restart/reset. Maintenance supplies
fresh health, Research supplies the recorded incident, Engineering examines the
pinned source, Security/Risk review a candidate, and Validation checks tests.
The existing candidate executor is still limited to breaker code; defects in
feeds, brokers or other modules require extending that scope with real evidence.

Acceptance requires diagnosing the actual failure, a justified repair or
operational correction, verified tests where applicable, reviewed deployment,
and fresh post-change TAS health evidence. A health flag alone is not sufficient.
Live deployment and breaker reset are not implemented by this transport change.
Verified incidents can later become evaluation cases for each specialist;
retaining receipts is not model training and no training has run here.

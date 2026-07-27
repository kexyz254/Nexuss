# P5 Web, Media, and Mobile Threat Model

## Protected assets

- Nexuss capability authority and approval state
- provider credentials
- paired-phone bearer sessions
- trusted-node signing secret
- user research queries and media selections
- Action Receipt integrity

## Principal threats and controls

### Prompt injection from retrieved pages

Retrieved text is stored only as source evidence. It is never passed to policy as an instruction and cannot register, approve, or invoke a capability.

### Malicious or deceptive URLs

Every browser and phone destination is parsed and restricted to HTTPS, approved hostnames, no embedded credentials, no fragments, bounded length, and deterministic query construction.

### Credential exposure

The YouTube API key is loaded only from the Core process environment. It is excluded from UI payloads, evidence, logs, receipts, manifests, and source-controlled templates.

### IFrame privilege escalation

The YouTube player is loaded from the provider’s documented origin. Core adds a restrictive Content Security Policy, denies framing of Nexuss itself, and exposes no privileged postMessage command receiver.

### Approval replay or payload substitution

Existing P4 controls remain mandatory: exact payload SHA-256, expiring one-time approval token, paired-session binding, signed device envelope, short command lifetime, and nonce replay protection.

### False execution claims

P5 distinguishes discovery, approved handoff, and verified native execution. The mobile-web handoff sets `app_open_verified` to false until a native signed companion can attest the result.

### Arbitrary browser or phone automation

Only registered Google/YouTube HTTPS handoffs are available. Shells, scripts, arbitrary executables, arbitrary Android intent extras, AccessibilityService automation, and payments remain prohibited.

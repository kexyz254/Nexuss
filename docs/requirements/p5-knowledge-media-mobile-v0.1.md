# P5 Knowledge, Media, and Mobile Requirements v0.1

## Functional requirements

- Classify research, YouTube discovery, phone YouTube handoff, and approved Chrome-search intents deterministically.
- Return bounded public sources, extracts, source URLs, provider identity, and a cited brief.
- Keep external source content marked as untrusted data.
- Keep research out of long-term memory unless a later explicit memory capability is approved.
- Discover up to five embeddable YouTube videos through the official Data API when configured.
- Accept a direct user-supplied YouTube video URL without requiring a search API key.
- Render a persistent player with queue, play/pause, previous/next, mute, minimize, maximize, and close controls.
- Require paired-phone approval before opening Chrome or handing a YouTube destination to the phone.
- Restrict handoffs to approved HTTPS hostnames and fixed execution shapes.
- Produce Action Receipts for research, discovery, and approved handoffs.

## Non-functional requirements

- Provider calls must use finite timeouts and ignore ambient proxy configuration.
- API credentials must not enter Git, browser JavaScript, logs, evidence, or receipts.
- UI responses must include restrictive security headers and isolate embedded content from privileged Core APIs.
- Unknown providers, malformed responses, quota failures, and unavailable services must fail honestly.
- P1–P4 behavior and security tests must remain green.

## Acceptance criteria

- Public research returns real source-labelled evidence under a mocked deterministic contract test and a live-provider runtime path.
- Missing YouTube configuration produces `YOUTUBE_API_KEY_NOT_CONFIGURED`, not fabricated results.
- Phone and Chrome actions remain `awaiting_approval` until the paired phone approves the exact payload hash.
- Malicious schemes, credentials in URLs, fragments, and non-allowlisted hosts are rejected.
- Complete repository validation, Ruff, MyPy strict, Bandit, and automated tests pass before merge.

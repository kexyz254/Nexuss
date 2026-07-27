# ADR-0007: P5 Knowledge, Media, and Mobile Action Plane

**Status:** Accepted for implementation on `feature/p5-knowledge-media-mobile`

## Context

P4 proved signed, phone-approved execution on a trusted Windows node. Nexuss now needs a governed path to current public information, user-selected media, and mobile app handoff without granting an AI model arbitrary browsing or device control.

## Decision

P5 introduces three separately registered capability families:

1. `knowledge.web_research` retrieves bounded public reference material through provider adapters. Retrieved text is untrusted evidence and cannot authorize tools.
2. `media.youtube.discover` uses the official YouTube Data API when configured and renders results through the official IFrame Player API.
3. `phone.open_youtube` and `device.open_web_search` perform exact, allowlisted HTTPS handoffs only after approval on the paired phone.

Provider keys remain server-side. Research is never saved to long-term memory automatically. Browser and phone handoffs are represented honestly: a handoff can be verified, but native app execution is not claimed until a signed native companion node can attest it.

## Consequences

- Nexuss gains current, source-labelled knowledge without treating websites as trusted instructions.
- Media playback remains inside the Nexuss interface while preserving provider controls.
- Android may route an approved HTTPS link to an installed app, but P5 remains a mobile-web handoff rather than unrestricted phone automation.
- Arbitrary URLs, shells, executables, Android intent components, and webpage-driven commands remain prohibited.

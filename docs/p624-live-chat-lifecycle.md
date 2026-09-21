# P6.24: Live chat lifecycle

Chat owns a turn until its governed task reaches a terminal state or status verification is blocked. Request routing and public decision summaries appear as live activity. Core task events and engineering telemetry continue after dispatch. The composer, voice input, attachments, and chat switching stay locked. Exact approval controls remain available without requiring another chat message.

The unified submission now awaits the task follower. Every desktop-approved action uses that follower, and phone approval is observed by the same polling loop. A static Executing response is no longer rendered as the final answer. Terminal results are refreshed into the durable conversation. Missing receipts render as pending rather than throwing. Partial completion, rejection, failure, and rollback all end following accurately.

Updates have a separate completion check: acceptance and a scheduled restart are not success. The local-control-protected update-result route exposes the retained result and running process SHA. Completion requires the approved target, retained active SHA, and running SHA to match. Rollback and recovery failure are surfaced explicitly. Verified restart reports are persisted when the interaction refreshes.

The browser retains task/interaction/conversation identifiers in session storage for refresh recovery. It only re-reads the task; it does not resubmit the action. Transient disconnections retry, while persistent loss produces an explicit unverified result and retains the identifiers. Poll requests have five-second network timeouts. Task-status following stops after 40 consecutive failures; restart verification stops after 160 attempts. Executing tasks have no artificial ten-minute completion cutoff.

Progress is based on emitted activity and evidence, not fabricated reasoning or simulated model tokens. This change does not add model token streaming. The composer lock is a browser-turn UX contract, not a cross-device execution mutex.

Validation: Node behavior tests cover locking, duplicate submission, approvals, all task outcomes, reconnects, refresh recovery, general progress events, and update verification. Python tests cover durable update reports and the protected result route, plus existing UI, interaction, and update regressions. Live Windows self-update and DPAPI-backed startup require verification on the installed runtime.

# Nexuss P4 Trusted Device Mesh Requirements v0.1

Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

1. Nexuss shall classify explicit Notepad launch requests deterministically.
2. The capability registry shall expose `device.launch_notepad` only as a registered high-risk capability.
3. Device commands shall require approval from a paired phone; desktop approval shall fail closed.
4. Pairing codes shall be random, single-use, session-bound, and expire within ten minutes.
5. Phone sessions shall use high-entropy bearer tokens, expire within eight hours, and remain revocable.
6. The phone shall display the exact action, target node, risk, reversibility, expiry, and payload SHA-256.
7. Nexuss Core shall not execute the command before phone approval.
8. The Windows node shall listen only on loopback.
9. Core-to-node envelopes shall be signed, expire within 30 seconds, and include replay-protected nonces.
10. The node shall reject any capability except the fixed Notepad launch capability.
11. The node shall never invoke a shell or accept a user-controlled executable path or argument.
12. Execution evidence shall identify the command, node, executable, process, timestamp, and verified running state.
13. The Action Receipt shall preserve the full request, policy, approval, execution, evidence, and rollback lifecycle.
14. Undo shall terminate only the process bound to the original command and task receipt.
15. The desktop shall poll and visibly update when the phone approves or denies the command.
16. Phone, desktop, Core, and node interactions shall be covered by unit, contract, integration, and security tests.
17. Private-LAN mode shall refuse startup when Windows has no active Private network profile.
18. No P4 service shall modify firewall rules, expose a public relay, or store shared secrets in source control.
19. Desktop control, task, receipt, rollback, and pairing-challenge endpoints shall accept loopback clients only.
20. The private-LAN listener shall expose only the phone approval surface, health, static assets, pairing submission, and authenticated phone-decision APIs.
21. Pairing submissions shall be rate-limited per client address.
22. Core shall reject any device-node URL that is not an unauthenticated loopback HTTP endpoint.
23. Device-client HTTP calls shall ignore ambient proxy configuration.
24. The ephemeral device-node secret shall be inherited through the child environment and shall not appear in process command-line arguments or runtime metadata.
25. Replay state shall retain each nonce until its envelope expires rather than clearing the full cache under load.

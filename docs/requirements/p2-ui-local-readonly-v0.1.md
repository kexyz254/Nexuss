# P2 UI and Local Read-Only Capability Requirements v0.1

1. The Nexuss API shall serve a same-origin control interface at `/`.
2. The interface shall accept typed instructions and submit them through the existing task lifecycle.
3. The interface shall support browser speech recognition when available and require review of the final transcript before execution.
4. The interface shall display intent, confidence, plan steps, policy decisions, evidence, task state, verification state, and receipt identifier.
5. The interface shall not insert dynamic values through unsafe HTML rendering.
6. The intent classifier shall recognize requests to inspect the local workspace or computer status.
7. The planner shall map that intent only to `workspace.read_status`.
8. Policy shall authorize `workspace.read_status` only as a low-risk read-only capability.
9. The provider shall derive the repository path internally and shall not accept a request-controlled path or command.
10. Git inspection shall use a fixed executable, no shell, allowlisted arguments, timeouts, and bounded output.
11. The provider shall not read user file contents, credentials, environment values, process lists, or network secrets.
12. Every live result shall identify `source_mode` as `live_local_readonly`.
13. Failed live evidence collection shall prevent a completed task state.
14. The existing P1 simulator capabilities and denial boundaries shall remain operational.
15. Unit, integration, contract, security, typing, lint, and repository validation gates shall pass before merge.

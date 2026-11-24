# WPT capability registration in Mission Stage 6

Mission's Stage 6.4 adapter contract now publishes two server-owned WPT profile
contracts: `wpt.fingerprinting.v1` and `wpt.bounded-enumeration.v1`. Each has an
independent action tuple, request/result schema, request and response budgets,
timeout, concurrency limit, redirect policy, and required evidence bindings.
They are included in the read-only adapter contract returned by Mission.

Both profiles currently have status `REGISTERED_NOT_EXECUTABLE`. The current
Stage 6.4 target broker and fixed parser worker support TCP connect, TCP banner,
and HTTP HEAD only. These WPT declarations therefore do not add active adapters,
do not authorize target I/O, and `select_adapter` continues to reject both
action tuples. This is intentional until the WPT-specific broker/worker path,
result validation, evidence capture, and governed action request are implemented
and tested in the next integration steps.

| Profile | Capability | Technique | Request cap | Response cap | Timeout |
|---|---|---|---:|---:|---:|
| Fingerprinting | `web_technology_fingerprinting` | `WEB_TECHNOLOGY_FINGERPRINT` | 6 | 327,680 bytes | 30 seconds |
| Bounded enumeration | `web_surface_enumeration` | `BOUNDED_WEB_SURFACE_ENUMERATION` | 12 | 262,144 bytes | 30 seconds |

Both require one worker, deny redirects, and require sealed Stage 6 evidence
bound to target, mission/task, action capability, execution ID, and result hash.

# Autonomous Mission to WPT intake

The Mission worker calls `mission_wpt_preparation.sweep()` every 30 seconds. Governed intake preparation is enabled by default; set `APTS_AUTONOMOUS_WPT_INTAKE=0` to disable it. To make intake rows visible in the WPT console, configure the authenticated inbox bridge:

```dotenv
APTS_AUTONOMOUS_WPT_INTAKE=1
APTS_WPT_INBOX_URL=http://127.0.0.1:8791
APTS_WPT_INBOX_TOKEN=<same secret as WTP_CLIENT_TOKEN; minimum 32 characters>
```

The worker reads Recon’s immutable `READY_FOR_COLLECTION` target declarations and accepts only records whose integrity seal, mission ID, current GSS snapshot, scope contract identity/version/hash, and exact URL membership all match. Once a planned Pentest orchestration task exists, it can prequeue the exact URL in WPT while Mission is `PLANNING`, `REPLANNING`, or `RUNNING`. WPT displays this record as **Menunggu task Pentest** and **Recon · belum diobservasi**. It is a declared target awaiting collection, not a scan result. The prequeue stays non-executable until the normal governed intake confirms a materialized `RUNNING` Pentest task and exactly one active orchestration; that confirmation promotes the same WPT record to **Menunggu Stage 6**. Any failed authority check is deferred; the worker does not create Pentest tasks, grant GSS permissions, or broaden scope.

## Important execution boundary

This enables automatic **submission to the governed WPT intake queue and visibility in the WPT console**, not automatic scanning. Current `WPT_CAPABILITY_PROFILES` still report `REGISTERED_NOT_EXECUTABLE`; `WPTIntakeService.submit()` writes `ACCEPTED_PENDING_STAGE6` and explicitly does not authorize or perform target I/O. Stage 6 remains the only scan execution boundary. Do not route the target to the standalone WPT profiler as a workaround; that would bypass the required Stage 6 authorization and evidence path.

The worker is idempotent: deterministic intake and idempotency identifiers are derived from Mission, Pentest task, Recon target key/hash, and profile. Repeated sweeps replay the stored intake rather than dispatching target I/O.

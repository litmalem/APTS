# Autonomous Recon delegation profile

The current APTS Control Center source already contains the Mission–WPT inbox bridge. This GSS change adds the organization-level delegation profile needed for autonomous Mission handoff after an authorized administrator enables it.

## Authorization boundary

The profile is disabled by default. When enabled, GSS adds an exact `TASK_DELEGATION/delegate_planned_task` ALLOW only to a newly issued or revised scope that already explicitly allows `TARGET_RECON`. It is limited to `PENTEST:pentest.recon`, with `execution_authorized=false` and `target_actuation=false`. Existing exact or wildcard `TASK_DELEGATION` rules remain authoritative, including DENY and REVIEW. The profile does not grant target access or authorize Stage 6 execution.

An authorized GSS administrator enables the profile in the GSS process environment:

```text
GSS_AUTO_RECON_TASK_DELEGATION=1
```

Restart GSS after changing the environment. For an existing mission, issue a new authenticated scope revision through the GSS UI/API using the current scope version. Do not edit GSS tables directly. Scope revisions remain versioned and audited. The Mission routing/handoff worker can then retry automatically against the latest scope and materialize its Pentest orchestration task.

## Mission–WPT inbox

The Control Center source provided with this patch base already contains `ensure_wpt_inbox_bridge()` and calls it before starting managed Mission or WPT processes. It persists one private shared token, derives the local inbox URL from the configured WPT port, and injects matching token settings into both processes. Restart Mission and WPT through the Control Center to load the settings. Conflicting explicit or persisted tokens stop startup and require explicit reconciliation.

## Recovery check

After the GSS scope revision and service restart, confirm the latest scope contains the exact delegation rule, Mission reports WPT intake configured, and WPT records the Recon intake. Mission may remain `PLANNING` until the orchestration task is materialized. WPT intake does not itself start a scan; Stage 6 execution remains separately governed.

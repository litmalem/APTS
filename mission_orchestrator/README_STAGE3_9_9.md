# Stage 3.9.9 — Global Observation / Reconstruction / Forensic Equivalence

## Status

Implementation candidate for host acceptance. Active control:
`stage3.9.9-global-observation-reconstruction-forensic-equivalence`.
Repository migration remains **53**. This stage introduces no new database migration,
durable store, observation authority, forensic authority, governance authority, runtime
execution authority, or target actuation.

## Purpose

Stage 3.9.9 proves that the already-qualified Stage 3.9.8 durable mission head has one
consistent global meaning when inspected through the independent Stage 3.8 observability
and forensic surfaces. It is an **equivalence verifier**, not another execution phase.

The canonical predecessor is the exact Stage 3.9.8 head:

- mission `RUNNING(v4)`;
- active Plan v2;
- one durable Stage 3.7.9 replan recovery checkpoint;
- 50 canonical Mission events;
- deterministic restart/replay/recovery already qualified;
- repository migration level 53.

## Equivalence model

For the same durable mission, Stage 3.9.9 independently reads the existing views and
requires exact agreement across:

```text
Durable Mission Event Ledger (50 events)
        │
        ├── Normalized Events (50)
        ├── Global Causal Graph (51 nodes / 50 edges)
        ├── Deterministic Timeline (50 event entries)
        ├── Decision / Governance / Evidence Trace
        ├── Live Mission Projection: RUNNING(v4), Plan v2
        ├── Integrity / Gap / Consistency Diagnostics: PASS
        └── Observability Health: HEALTHY
                         │
                         ▼
              Source-bound Forensic Bundle
                         │
            ┌────────────┼─────────────┐
            ▼            ▼             ▼
      Reconstruction  Event Query  Lineage/Integrity Query
            │            │             │
            └────────────┴─────────────┘
                         ▼
              GLOBAL EQUIVALENCE = PASS
```

The verifier requires the raw event ledger, normalized events, and deterministic timeline
to carry the same ordered `(event_id, canonical_sha256, event_type)` references. The same
global trace identity and canonical event-tip hash must remain consistent across the direct
observability views, forensic bundle, reconstruction, and forensic query results.

## Single-snapshot forensic rule

The service obtains one verified Stage 3.8.9 forensic evidence bundle and derives the
reconstruction plus event/lineage/integrity query slices from that exact bundle. Direct
observability views are rebuilt independently and compared to the source-bound bundle.
This prevents equivalence from being masked by multiple independently refreshed forensic
snapshots.

The bundle remains **source-bound evidence**, not external attestation. Reconstruction is
read-only: it is not mission re-execution, runtime resumption, recovery mutation, or
integrity repair.

## Fail-closed behavior

Qualification is rejected when any required invariant drifts, including:

- predecessor Stage 3.9.8 is not qualified;
- event/repository integrity fails;
- raw, normalized, timeline, or forensic event references diverge;
- causal graph cardinality or source binding diverges;
- direct observability views differ from the forensic bundle sources;
- durable state, active plan, or event records differ from the forensic bundle records;
- reconstruction or forensic query output is not an exact derivation of the same bundle;
- trace identity or event-tip hash diverges;
- diagnostics are not `PASS`, blocking findings are present, or observability health is not
  `HEALTHY`.

## Read-only APIs

```text
GET /api/e2e/observation-reconstruction-forensic-equivalence-contract
GET /api/missions/{mission_id}/e2e-observation-reconstruction-forensic-equivalence
```

The mission qualification route does not rerun the planner, query Governance or execution
runtime, route/delegate work, dispatch, create an execution attempt, transition mission
state, export telemetry, perform external network I/O, repair integrity, or actuate a target.

## Acceptance

After copying the overlay into `D:\mission_orchestrator`, restart the application and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_9_ACCEPTANCE.ps1
```

Canonical inventory: **1560 tests**. Focused Stage 3.9.9 suite: **15 tests** covering
contract integrity, active-control health, exact 50-event cross-view equivalence,
forensic-source binding, exact reconstruction/query derivation, trace/tip identity,
restart stability, read-only boundaries, source-drift rejection, canonical-event tamper
rejection, and HTTP routes.

Next stage: **3.9.10 — Final Acceptance & Regression Gate**.

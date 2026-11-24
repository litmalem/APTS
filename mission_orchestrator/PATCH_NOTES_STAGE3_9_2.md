# Patch Notes — Stage 3.9.2

## Runtime control

`stage3.9.2-intake-lifecycle-e2e-segment-qualification`

## Added

- `mission_orchestrator/e2e_intake_lifecycle_qualification.py`
  - immutable/versioned Intake → Lifecycle qualification contract;
  - source binding to the frozen Stage 3.9.1 acceptance-contract digest;
  - exact `CREATED(v1) → PIP_BOUND(v2) → PLANNING(v3)` sequence;
  - deterministic Stage 3.9.2 lifecycle command builder;
  - exact transition, command, Mission-event, identity, activation, and repository-footprint verifier;
  - fail-closed rejection of partial/noncanonical trajectories;
  - restart-stable read-only qualification from persisted evidence.
- `GET /api/e2e/intake-lifecycle-qualification-contract`.
- `GET /api/missions/{mission_id}/e2e-intake-lifecycle-qualification`.
- Stage 3.9.2 health/diagnostic fields.
- 15 focused Stage 3.9.2 tests.
- `STAGE3_9_2_ACCEPTANCE.ps1`.

## Changed

- Runtime control advances from Stage 3.9.1 to Stage 3.9.2.
- HTTP server version advances to `APTSMissionOrchestrator/3.9.2`.
- `supported_controls` preserves Stage 3.9.1 as the immediate predecessor and appends Stage 3.9.2.
- Historical tests that intentionally assert the active runtime head/server version are rebased to Stage 3.9.2 while retaining historical stage identities and ordering.
- Package module description is advanced through Stage 3.9.2.

## Qualified runtime semantics

The acceptance harness executes the existing canonical Stage 3.9.1 Mission request and existing lifecycle commands only:

1. Mission registration establishes `CREATED`, state version 1.
2. `BIND_PIP` establishes `PIP_BOUND`, state version 2.
3. `START_PLANNING` establishes `PLANNING`, state version 3.

At the Stage 3.9.2 head there is no planner invocation, no plan artifact, no task graph, no routing/delegation artifact, no dispatch/execution artifact, and no outcome/replan artifact.

Exact replay must remain idempotent with the same Mission root and the same 2 transitions, 2 commands, and 5 events.

## Deliberately unchanged

- Repository migration level: **53**.
- Database schema: no migration 054.
- Durable persistence stores: none added.
- Governance authority: unchanged.
- Routing/delegation/dispatch/execution authority: unchanged.
- Planner authority: unchanged; Stage 3.9.2 does not invoke the planner.
- External network I/O and telemetry export: not introduced.
- Target actuation authority: not introduced.

## Regression inventory

The canonical inventory increases from **1443** to **1458** tests (+15 Stage 3.9.2 tests).

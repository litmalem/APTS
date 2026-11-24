# Patch Notes — Stage 3.3.2 Planner Input Snapshot & Context Binding

## Added

- `mission_orchestrator/planner_input_snapshot.py`
  - canonical planner-input snapshot schema/constants;
  - strict binding-only request normalization;
  - request fingerprinting;
  - stable `mpis-*` snapshot identity;
  - deterministic context assembly from durable local canonical facts;
  - exact Mission/Plan/lifecycle/Scope/Governance/PIP context binding;
  - source-context SHA-256 and full snapshot SHA-256 integrity verification;
  - static snapshot-contract discovery definition.
- `migrations/010_stage3_3_2_planner_input_snapshot_context_binding.sql`
  - durable `mission_planner_input_snapshots` store;
  - repository migration level `10`.
- New canonical errors for snapshot conflict, not-found, and guard rejection.
- `MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED` canonical Mission event.
- Planner-input snapshot registration/read/discovery APIs.
- `planner_input_snapshot_version` in the canonical Mission version vector.
- Planner-input snapshot store in repository reconstruction, persistence manifest, record counts, and integrity checks.
- `tests/test_stage3_3_2_planner_input_snapshot_context_binding.py` with **16 focused tests**.
- `STAGE3_3_2_ACCEPTANCE.ps1` and Stage-3.3.2 release documentation.

## Changed

- Current control advances to `stage3.3.2-planner-input-snapshot-context-binding`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.3.2`.
- Repository migration level advances `9 -> 10`.
- Repository store manifest adds `mission_planner_input_snapshots`.
- Repository core signature includes the canonical planner-input snapshot.
- Historical regression assertions recognize Stage 3.3.2 as the current runtime while retaining Stage 3.3.1 as the canonical Plan prerequisite.
- Package description advances through Stage 3.3.2.

## Guard semantics

- Stage-3.3.1 Plan is mandatory and must pass integrity verification.
- Exact Plan id/version/SHA-256 and exact Mission state version are concurrency tokens.
- Snapshot creation is restricted to the exact Plan-bound `PLANNING` state/version.
- Stage-3.2.4 planning activation lineage is revalidated.
- Scope drift after Plan registration blocks snapshot construction.
- A locally persisted Governance binding, when present, must remain aligned with the exact current Plan-bound Scope.
- Context is read from the local canonical repository only; no CTI/Governance refresh is performed.

## Preserved

- Stage 3.1 canonical Mission identity/state/scope/governance/event contracts.
- Stage 3.2 lifecycle topology, guards, activation, waiting, pause/resume/replan, terminal semantics, cleanup/completion, automation, and closure gate.
- Stage 3.3.1 canonical immutable Plan identity and its `NOT_MATERIALIZED` task graph.
- `EXTERNAL_APTS_GSS` as sole Governance/authorization authority.
- No planner invocation, Plan synthesis, task decomposition, Plan revision, target dispatch, or target actuation.

## Canonical invariants

- `SNAPSHOT != AUTHORIZATION`
- `CONTEXT != PERMISSION`
- `PLAN != AUTHORIZATION`
- `TASK != DISPATCH`
- `READINESS != PERMISSION`
- `PLANNER != GOVERNANCE`

## Validation

- Python compile: PASS.
- Focused Stage-3.3.2 tests: **16 passed**.
- Full Stage-3 regression: **296 passed**.
- Live acceptance entry point: `STAGE3_3_2_ACCEPTANCE.ps1`.

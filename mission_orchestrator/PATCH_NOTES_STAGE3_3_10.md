# Patch Notes — Stage 3.3.10 Planning Acceptance & Regression Gate

## Added

- `mission_orchestrator/planning_acceptance_gate.py`
  - static Stage-3.3 closure contract;
  - required prior-control declaration;
  - required external acceptance gates;
  - explicit no-authority/no-persistence-expansion semantics.
- Stage-3.3 closure metadata in `/health`.
- `tests/test_stage3_3_10_planning_acceptance_regression_gate.py` with 12 closure/integration cases.
- `STAGE3_3_10_ACCEPTANCE.ps1` for full regression plus live canonical planning probes.
- Stage-3.3.10 README, install guide, manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.3.10-planning-acceptance-regression-gate`;
- HTTP server identity -> `APTSMissionOrchestrator/3.3.10`;
- package declaration -> through Stage 3.3.10;
- historical regression assertions that intentionally track the current control or supported-control tail are rebased to Stage 3.3.10.

## Preserved

- all Stage-3.3.1–3.3.9 canonical planning artifacts and persistence semantics;
- local deterministic Stage-3.3.5 planner behavior;
- repository migration level `17`;
- latest migration `017_stage3_3_9_planning_event_lineage_replay_recovery.sql`;
- append-only Plan-version lineage;
- readiness as structural projection only;
- read-only planning replay;
- durable recovery without planner rerun;
- `EXTERNAL_APTS_GSS` as the sole Governance authorization authority;
- no wall-clock/resource scheduling;
- no task/target dispatch or target actuation.

## Validation

Verified partitioned regression coverage:

```text
111 + 156 + 77 + 57 + 27 + 28 + 38 + 12 = 506 passed
```

Focused Stage-3.3.10 regression: `12 passed`.

Collection check: `506 tests collected`.

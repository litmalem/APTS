# Patch Notes — Stage 3.4.10 Routing & Delegation Acceptance / Regression Gate

## Added

- `mission_orchestrator/routing_delegation_acceptance_gate.py`
  - static Stage-3.4 closure contract;
  - ordered Stage-3.4.1–3.4.9 prerequisite controls;
  - mandatory external acceptance gates;
  - explicit no-new-authority / no-new-execution / no-new-persistence semantics.
- Stage-3.4 closure metadata in `/health`.
- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
  - 12 closure and integration tests;
  - end-to-end Stage-3.4.1–3.4.9 artifact chain;
  - restart, lineage, replay, repository/event integrity, and authority-boundary proofs.
- `STAGE3_4_10_ACCEPTANCE.ps1`
  - runtime activation preflight;
  - Python compile gate;
  - full regression gate;
  - focused Stage-3.4.10 proof;
  - live runtime closure and authority-boundary checks.
- Stage-3.4.10 README, install guide, manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.4.10-routing-delegation-acceptance-regression-gate`;
- HTTP server identity -> `APTSMissionOrchestrator/3.4.10`;
- package declaration -> through Stage 3.4.10;
- supported-control tail now explicitly contains Stage 3.4.1 through Stage 3.4.10;
- historical regression assertions that intentionally track the active/current control or server identity are rebased to Stage 3.4.10.

## Preserved

- all Stage-3.4.1–3.4.9 routing/delegation artifacts and persistence semantics;
- canonical registry and capability contracts;
- candidate resolution from the canonical registry;
- static eligibility and compatibility gating;
- deterministic logical route selection and decision records;
- external Governance authority for delegation authorization;
- immutable delegation contract and handoff envelope;
- delivery / acknowledgement / control-plane ownership receipts;
- bounded retry / fallback / reassignment / conflict-control contracts;
- routing/delegation event lineage, deterministic read-only replay, and durable recovery;
- Mission event hash-chain integrity;
- repository manifest/integrity accounting;
- repository migration level `26`;
- latest migration `026_stage3_4_9_routing_delegation_event_lineage_replay_recovery.sql`;
- no target-action dispatch and no target actuation.

## Explicit non-features of Stage 3.4.10

Stage 3.4.10 does not add:

- a subsystem or capability;
- candidate-resolution behavior;
- route-selection authority;
- Governance decision authority;
- delegation or ownership-transfer authority;
- runtime endpoint resolution;
- runtime health probing;
- execution resource allocation;
- task dispatch;
- execution authorization;
- target-action dispatch;
- target actuation;
- external network I/O;
- a durable repository store;
- a database migration.

## Test cardinality

- Previous Stage-3.4.9 full baseline: `767` tests.
- New Stage-3.4.10 tests: `12`.
- Expected full Stage-3.4.10 regression cardinality: `779`.
- Focused Stage-3.4.10 construction-time verification: `12 passed`.

The canonical target-host PASS result is produced only by `STAGE3_4_10_ACCEPTANCE.ps1`.

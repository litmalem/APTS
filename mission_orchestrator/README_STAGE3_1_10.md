# Stage 3.1.10 — Acceptance & Regression Gate

## Purpose

Stage 3.1.10 closes **Stage 3.1 — Canonical Mission Contract & State** for the Global Mission Orchestrator (`APTS-MO01`). It is intentionally a **release/closure gate**, not a new autonomy feature.

The stage proves that the capabilities introduced in Stage 3.1.1 through Stage 3.1.9 still compose correctly as one canonical Mission control plane:

1. immutable Mission identity and envelope;
2. canonical Mission state and optimistic concurrency;
3. Scope / Rules of Engagement / Constraint contract;
4. external Governance and authorization binding;
5. governed subsystem routing without target-action authority;
6. multi-domain Mission version vector and idempotent command gate;
7. durable repository reconstruction and integrity checking;
8. stabilized Canonical Mission API and zero-side-effect preflight validation;
9. append-only Mission event ledger and local lineage projection.

Stage 3.1.10 adds **no planner, no target execution path, no new policy authority, no new durable store, and no database migration**.

## Closure contract

The runtime now advertises:

- `control_version = stage3.1.10-acceptance-regression-gate`
- `stage3_1_acceptance_gate_schema_version = apts-mission-stage3.1-acceptance-gate-v1`
- `stage3_1_acceptance_gate_mode = FULL_REGRESSION_PLUS_LIVE_CONTRACT_PROBES`
- `stage3_1_acceptance_gate_baseline = STAGE_3_1_1_THROUGH_3_1_9`
- `stage3_1_acceptance_gate_runtime_change_mode = NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY`
- `stage3_1_acceptance_gate_database_change_mode = NO_NEW_DATABASE_MIGRATION`
- `stage3_1_acceptance_gate_expected_migration_level = 8`
- `stage3_1_acceptance_gate_declared_only = true`
- `stage3_1_acceptance_gate_runtime_self_certification = false`
- `stage3_1_acceptance_gate_external_execution_required = true`

The distinction between **declaring** the gate and **passing** the gate is deliberate. `/health` never self-certifies that acceptance has run. The actual PASS/FAIL decision is produced by the external regression/acceptance execution.

## Required release gates

The Stage-3.1 closure contract requires:

1. `PYTHON_COMPILE`
2. `FULL_PYTEST_REGRESSION`
3. `MISSION_HEALTH_AND_AUTHORITY_BOUNDARY`
4. `GOVERNANCE_READINESS_AND_EMERGENCY_STOP`
5. `CTI_READINESS`
6. `CANONICAL_PREFLIGHT_ZERO_SIDE_EFFECTS`
7. `IDENTITY_IDEMPOTENCY_AND_STATE_CONCURRENCY`
8. `SCOPE_ROE_CONSTRAINT_IMMUTABILITY`
9. `GOVERNANCE_BINDING_AND_AUTHORIZATION_PROVENANCE`
10. `GOVERNED_CTI_ROUTING_AND_REPLAY`
11. `VERSION_VECTOR_AND_COMMAND_GATE`
12. `EVENT_LINEAGE_AND_REPOSITORY_INTEGRITY`
13. `FINAL_NO_TARGET_EXECUTION_AUTHORITY`

## Authority boundaries preserved

Stage 3.1.10 keeps the architecture established by prior stages:

- `APTS-MO01` owns the canonical global Mission identity, lifecycle, contracts, local routing records, version-vector/command journal, persistence model, and local Mission event ledger.
- `aptsGSS / GOV-PLANE` remains the sole policy, approval, revocation, hard-deny, and emergency-stop authority.
- VulnDesk/CTI remains authoritative for CTI-local `state_version` and `plan_version`.
- Governed subsystem routing to CTI remains a control-plane handoff, not target-action dispatch.
- `dispatch_enabled = false`
- `target_action_dispatch_enabled = false`
- `target_actuation = false`
- downstream target actions still require authoritative pre-dispatch Governance revalidation.

## Database / persistence compatibility

Stage 3.1.10 adds no migration.

The repository remains at:

- schema version: existing Stage-3.1.7 repository schema;
- migration level: **8**;
- latest migration: `008_stage3_1_9_mission_event_lineage_foundation.sql`.

No `009` migration is expected for this stage.

## New Stage-3.1.10 test coverage

`tests/test_stage3_1_10_acceptance_regression_gate.py` adds ten closure tests covering:

- health and release-gate metadata;
- zero-side-effect canonical preflight followed by real persistence;
- idempotent replay across Mission create, Scope, Governance binding, and governed routing task;
- legal lifecycle completion plus illegal/stale transition rejection;
- authoritative Governance authorization provenance and policy-version observation;
- safe internal CTI routing, target-route fail-closed behavior, and dispatch replay;
- stale version-vector command rejection and command journaling;
- restart/reconstruction from durable repository state without external reads;
- fail-closed event/repository integrity after tampering;
- closure contract consistency and explicit absence of a Stage-3.1.10 migration.

Patch-local result:

- `python -m compileall -q mission_orchestrator tests` — PASS
- `python -m pytest -q` — **111 passed**

## Live acceptance

`STAGE3_1_10_ACCEPTANCE.ps1` is the authoritative live closure script. It expects the three services at their standard local endpoints unless overridden:

- Mission Orchestrator: `http://127.0.0.1:8780`
- Governance: `http://127.0.0.1:8770`
- VulnDesk CTI: `http://127.0.0.1:8765`

The script performs:

1. compile + 111-test regression;
2. Mission health and closure metadata verification;
3. Governance/CTI readiness and emergency-stop safety check;
4. four-layer canonical preflight with zero side effects;
5. Mission create/idempotent replay/root event;
6. immutable Scope contract/replay/canonical projection;
7. Governance binding and authoritative in-scope authorization provenance;
8. canonical state progression, governed CTI route, target-route negative gate, and idempotent CTI dispatch;
9. complete version vector, successful/replayed guarded command, and stale command rejection;
10. Mission event/lineage/repository integrity closure;
11. final authority and target-execution invariant.

The acceptance script **will not disable an active Governance emergency stop**. If the emergency stop is active, it fails closed and requires an administrative decision outside this patch.

## Expected final output

```text
==============================================================================
STAGE 3.1.10 ACCEPTANCE: PASS
==============================================================================
```

When that gate passes, Stage 3.1 is closed and the implementation can move to the next Stage-3 workstream without treating Stage 3.1 as incomplete.

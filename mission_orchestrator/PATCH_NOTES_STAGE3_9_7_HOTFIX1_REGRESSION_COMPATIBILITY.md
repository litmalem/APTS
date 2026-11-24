# Stage 3.9.7 Hotfix 1 — Regression Compatibility

## Trigger

The authoritative Windows acceptance run for Stage 3.9.7 passed all gates before the final historical regression:

- runtime activation: PASS;
- Stage 3.9.7 contract route: PASS;
- Python compilation: PASS;
- canonical inventory: `1531 tests collected`;
- focused Stage 3.9.7: `16 passed`;
- Stage 3.9 E2E predecessor chain: `100 passed`;
- adaptation / replanning authority regression: `200 passed`.

The final historical regression completed with:

- `26 failed`;
- `1505 passed`;
- inventory unchanged at `1531`.

The failures separate into two compatibility classes.

## Class A — stale supported-controls regression expectations

Nine historical assertions still modeled the suffix as:

`... -> Stage 3.9.5 -> CURRENT_CONTROL`

After activation of Stage 3.9.7, the canonical control chain is:

`... -> Stage 3.9.5 -> Stage 3.9.6 -> Stage 3.9.7`

The runtime chain was already correct; only predecessor regression expectations were stale. This hotfix rebases exact lists, suffix slice cardinalities, absolute indexes, negative indexes, and uniqueness/cardinality assertions to preserve Stage 3.9.6 as the immediate predecessor of Stage 3.9.7.

## Class B — Stage 3.8 observability backward-compatibility regression

Stage 3.9.7 changed the live mission-state execution projection from:

`repository.list_plan_versions(mission_id)`

to:

`get_plan_version_history(mission_id)["plan_versions"]`.

The latter is a strict version-history API and raises `MissionPlanVersioningNotFound` for valid historical missions that have no plan-version rows. Stage 3.8 observability/forensics intentionally supports such sparse missions and represents absent planning data as an empty collection.

The strict lookup therefore broke Stage 3.8.4/3.8.7/3.8.8/3.8.9/3.8.10 read-only observability paths and surfaced as both direct `MissionPlanVersioningNotFound` failures and HTTP 404 responses.

Hotfix 1 restores the original read-only projection behavior:

`plan_versions=self.repository.list_plan_versions(mission_id)`

This does not weaken Stage 3.9.7 qualification because the Stage 3.9.7 qualification path still uses the strict `get_plan_version_history()` call where an actual versioned replan trajectory is required.

## Scope

Runtime file changed:

- `mission_orchestrator/service.py`

Historical regression files rebased:

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`
- `tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py`
- `tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py`
- `tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py`
- `tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py`
- `tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py`

## Invariants preserved

- active control remains `stage3.9.7-adaptation-replanning-e2e-scenario`;
- repository migration remains `53`;
- canonical inventory remains `1531`;
- no new durable store;
- no new database migration;
- no new replanning authority;
- Stage 3.9.6 remains the predecessor of Stage 3.9.7;
- Stage 3.8 projection remains read-only and can represent a mission with zero plan versions;
- Stage 3.9.7 strict replan qualification still requires a valid versioned planning/replanning trajectory.

## Local qualification

- modified Python files compile: PASS;
- canonical collection: `1531 tests collected`;
- exact 26 Windows-host failing node IDs: `26 passed in 13.63s`;
- focused Stage 3.9.7 batch 1: `8 passed in 22.82s`;
- focused Stage 3.9.7 batch 2: `8 passed in 27.47s`;
- runtime health probe: control `stage3.9.7-adaptation-replanning-e2e-scenario`, migration `53`, suffix contains `3.9.1 -> ... -> 3.9.6 -> 3.9.7`.

The complete 1531-test historical regression was not rerun in the sandbox because the authoritative host run requires tens of minutes. Final closure therefore requires rerunning the existing Stage 3.9.7 acceptance gate on Windows.

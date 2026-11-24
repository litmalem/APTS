# Patch Notes — Stage 3.6.10

## Stage

**3.6.10 — Outcome Acceptance / Regression Gate**

## Active runtime identity

```text
control_version = stage3.6.10-outcome-acceptance-regression-gate
server_version  = APTSMissionOrchestrator/3.6.10
repository_migration_level = 44
```

## Changes

### 1. Added declarative Stage-3.6 closure contract

New module:

```text
mission_orchestrator/outcome_acceptance_gate.py
```

It declares the complete Stage-3.6.1 through Stage-3.6.9 prerequisite chain, 17 external acceptance gates, the canonical Stage-3.6 authority boundaries, and explicit no-new-authority/no-new-runtime-I/O/no-new-persistence properties.

The contract is intentionally declarative:

```text
declared_only = true
runtime_self_certification = false
external_acceptance_execution_required = true
```

### 2. Activated Stage-3.6.10 runtime identity

`mission_orchestrator/service.py` now exposes:

```text
stage3.6.10-outcome-acceptance-regression-gate
```

with Stage 3.6.9 as the immediate predecessor.

`mission_orchestrator/api_service.py` now reports:

```text
APTSMissionOrchestrator/3.6.10
```

### 3. Added closure metadata to `/health`

The health model now declares the closure schema/mode/baseline, exact prerequisite controls and mandatory gates, expected migration level 44, external acceptance requirement, and the final authority matrix.

All Stage-3.6.10 `new_*` authority/I/O/persistence fields are `false`. The only existing Mission-success completion-authority marker retained as `true` is:

```text
stage3_6_outcome_acceptance_gate_verified_completion_is_mission_success_completion_authority
```

which points to Stage 3.6.8 rather than creating new authority in Stage 3.6.10.

### 4. Added focused Stage-3.6 closure/integration proof

New test file:

```text
tests/test_stage3_6_10_outcome_acceptance_regression_gate.py
```

It adds 12 tests covering success trajectory closure, blocked non-success readiness, lineage/replay/recovery consistency, restart reconstruction, repository integrity, exact authority boundaries, and no-new-migration/store guarantees.

### 5. Rebased historical current-head assertions

Historical tests that explicitly assert current `control_version`, `server_version`, or positional `supported_controls` tail were rebased to the Stage-3.6.10 head. Historical stage semantics are unchanged.

## Database / persistence

No Stage-3.6.10 database migration is added:

```text
latest migration = 044_stage3_6_9_outcome_lineage_replay_recovery.sql
migration level  = 44
new durable store = NONE
```

## Authority model preserved

```text
3.6.1 task outcome materialization                    != task completion
3.6.2 terminality/eligibility                        != task acceptance
3.6.3 evidence verification                          != task completion
3.6.4 dependency-aware task completion               != Mission completion
3.6.5 Mission outcome aggregation                    != success evaluation
3.6.6 success-criteria evaluation                    != completion authority
3.6.7 completion readiness                           != completion authority
3.6.8 verified completion declaration                = Mission-success completion authority
3.6.9 replay/recovery                                = read-only reconstruction only
3.6.10 acceptance declaration                        != outcome processing/completion authority
```

## Regression cardinality

```text
previous Stage-3.6.9 inventory = 1144 tests
new Stage-3.6.10 tests         = 12 tests
expected canonical inventory   = 1156 tests
expected Stage-3.6 chain       = 193 tests
```

Package-construction verification:

```text
compileall                                   PASS
collect-only                                1156 tests
Stage-3.6.10 focused                        12 passed
Stage-3.5.10 current-head tail assertion    1 passed
Stage-3.4.10 current-head tail assertion    1 passed
```

The complete 1156-test regression is intentionally re-executed by `STAGE3_6_10_ACCEPTANCE.ps1` on the target host. The sandbox did not complete a full regression within its available execution window, so no full-regression PASS is claimed in these patch notes.

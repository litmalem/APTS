# Stage 3.6.10 — Outcome Acceptance / Regression Gate

## Purpose

Stage 3.6.10 is the **closure gate for Stage 3.6 — Task Outcome, Completion, Mission Outcome, and Verified Completion**. It introduces no new outcome-processing primitive and no new completion authority. Its purpose is to freeze the Stage-3.6 semantics and require external acceptance evidence that the complete Stage-3.6.1 through Stage-3.6.9 chain still composes correctly.

The closure proves that the system can:

1. materialize a canonical task outcome without silently accepting or completing the task;
2. classify terminality and completion eligibility deterministically without creating acceptance authority;
3. verify evidence bindings without dereferencing/reinterpreting content or committing task completion;
4. commit dependency-aware task completion without promoting it to Mission completion;
5. aggregate Mission outcome without evaluating success criteria;
6. evaluate Mission success criteria without deciding completion readiness or completing the Mission;
7. derive completion readiness/blockers without becoming completion authority;
8. declare verified Mission completion only through the Stage-3.6.8 authority and hand off through the canonical Stage-3.2 lifecycle path;
9. reconstruct the completed trajectory through Stage-3.6.9 lineage, read-only replay, and durable recovery without runtime/Governance contact, redispatch, resumption, lifecycle transition, or target actuation; and
10. prove through regression/integration evidence that Stage 3.6.10 itself adds no new outcome authority, completion authority, runtime I/O, lifecycle path, durable store, or database migration.

## Architectural position

```text
Stage 3.6.1  Canonical Task Outcome Contract & Identity
      |
Stage 3.6.2  Task Terminality & Completion Eligibility
      |
Stage 3.6.3  Evidence Binding Verification
      |
Stage 3.6.4  Dependency-Aware Task Completion
      |
Stage 3.6.5  Mission Outcome Aggregation
      |
Stage 3.6.6  Mission Success Criteria Evaluation
      |
Stage 3.6.7  Completion Readiness & Blockers
      |
Stage 3.6.8  Verified Completion Declaration & Lifecycle Handoff
      |
Stage 3.6.9  Outcome Lineage, Replay & Recovery
      |
Stage 3.6.10 Outcome Acceptance / Regression Gate
      |
      +--> external full regression + canonical outcome integration
           + completion-authority boundary proof
           no new outcome processing
           no new Mission-success authority
           no new Governance/runtime I/O
           no new dispatch / actuation
           no new lifecycle path
           no new durable store / migration
```

## Runtime identity

```text
control_version = stage3.6.10-outcome-acceptance-regression-gate
server_version  = APTSMissionOrchestrator/3.6.10
repository_migration_level = 44
new_database_migration = none
new_durable_store = none
```

Stage 3.6.9 remains the newest persistence addition:

```text
migration 044
mission_outcome_recovery_checkpoints
```

## Closure contract

The static closure contract is implemented in:

```text
mission_orchestrator/outcome_acceptance_gate.py
```

Contract identity:

```text
schema_version = apts-mission-stage3.6-outcome-acceptance-gate-v1
mode = FULL_REGRESSION_PLUS_CANONICAL_OUTCOME_INTEGRATION_AND_LIVE_COMPLETION_BOUNDARY_PROBES
baseline = STAGE_3_6_1_THROUGH_3_6_9
runtime_change_mode = NO_NEW_OUTCOME_COMPLETION_AUTHORITY_RUNTIME_IO_OR_TARGET_ACTUATION
database_change_mode = NO_NEW_DATABASE_MIGRATION
expected_repository_migration_level = 44
```

The runtime exposes the declaration through `/health`, but **does not self-certify acceptance**:

```text
declared_only = true
runtime_self_certification = false
external_acceptance_execution_required = true
```

## Required prior controls

Stage 3.6.10 requires this complete ordered chain:

```text
stage3.6.1-canonical-task-outcome-contract-identity
stage3.6.2-task-terminality-completion-eligibility
stage3.6.3-evidence-binding-verification
stage3.6.4-dependency-aware-task-completion
stage3.6.5-mission-outcome-aggregation
stage3.6.6-mission-success-criteria-evaluation
stage3.6.7-completion-readiness-blockers
stage3.6.8-verified-completion-declaration-lifecycle-handoff
stage3.6.9-outcome-lineage-replay-recovery
```

## Exact authority boundary

Stage 3.6.10 freezes this division of responsibility:

```text
3.6.1  materializes canonical task outcome; NOT task completion
3.6.2  classifies terminality/eligibility; NOT task acceptance
3.6.3  verifies evidence binding; NOT task completion
3.6.4  commits dependency-aware task completion; NOT Mission completion
3.6.5  aggregates Mission outcome; NOT success evaluation
3.6.6  evaluates success criteria; NOT completion-readiness authority
3.6.7  decides readiness/blockers; NOT Mission-success completion authority
3.6.8  is the sole Stage-3.6 Mission-success completion authority and uses the
       canonical Stage-3.2 lifecycle-command path; no direct state bypass
3.6.9  replay/recovery is read-only durable reconstruction; NOT completion,
       dispatch, runtime resumption, Governance authorization, or lifecycle transition
3.6.10 declaration/acceptance only; NOT outcome processing or completion authority
```

Critical semantic separations remain:

```text
TASK OUTCOME != TASK COMPLETION
TERMINALITY != TASK ACCEPTANCE
EVIDENCE VERIFICATION != TASK COMPLETION
TASK COMPLETION != MISSION COMPLETION
MISSION OUTCOME AGGREGATION != SUCCESS EVALUATION
SUCCESS EVALUATION != COMPLETION AUTHORITY
COMPLETION READINESS != COMPLETION AUTHORITY
REPLAY != OUTCOME PROCESSING
RECOVERY != COMPLETION / DISPATCH / RUNTIME RESUMPTION / LIFECYCLE TRANSITION
CLOSURE GATE != OUTCOME PROCESSING / COMPLETION AUTHORITY
```

## Required acceptance gates

The static Stage-3.6.10 contract declares 17 mandatory gates:

1. Python compile.
2. Canonical pytest inventory.
3. Full pytest regression.
4. Mission health and authority-boundary verification.
5. Canonical task-outcome contract/identity verification.
6. Task terminality/completion-eligibility verification.
7. Evidence-binding verification.
8. Dependency-aware task-completion verification.
9. Mission-outcome aggregation verification.
10. Mission-success criteria evaluation verification.
11. Completion-readiness/blocker verification.
12. Verified-completion declaration/lifecycle-handoff verification.
13. Outcome-lineage/replay/recovery verification.
14. Success and blocked non-success trajectory integration.
15. Restart reconstruction without runtime/Governance redispatch or resumption.
16. Repository/event-integrity verification.
17. Final outcome/completion-authority, runtime-I/O, and actuation-boundary proof.

## Persistence closure

No migration `045` is added. The Stage-3.6 durable stores remain those introduced by Stages 3.6.1–3.6.9:

```text
mission_task_outcomes
mission_task_terminality_eligibility_gates
mission_task_evidence_binding_verifications
mission_task_completion_commits
mission_outcome_aggregations
mission_success_criteria_evaluations
mission_completion_readiness_decisions
mission_verified_completion_declarations
mission_outcome_recovery_checkpoints
```

Stage 3.6.10 adds no persistence table/store of its own.

## Acceptance test coverage

`tests/test_stage3_6_10_outcome_acceptance_regression_gate.py` adds 12 closure/integration tests covering:

- Stage-3.6.10 runtime identity, closure metadata, and unchanged migration level 44;
- completeness of the static closure contract and all 17 mandatory gates;
- complete success trajectory across Stage 3.6.1 → 3.6.9;
- causal outcome lineage, replay, and durable recovery consistency;
- read-only replay/recovery with no repository mutation or runtime/Governance contact;
- restart reconstruction from durable state only;
- blocked `FAILED`/`ABORTED` terminal trajectories that cannot become completion-ready;
- exact Stage-3.6 completion-authority matrix, preserving Stage 3.6.8 as the only Mission-success authority;
- Stage-3.6 repository manifest and integrity closure;
- absence of migration 045 and absence of a Stage-3.6.10 store;
- no new outcome authority/runtime I/O/lifecycle path/actuation from the closure gate; and
- complete ordered Stage-3.6.1 through Stage-3.6.10 supported-control tail with no runtime self-certification.

The Stage-3.6.9 package contained 1144 tests. Stage 3.6.10 adds 12 tests:

```text
expected canonical regression inventory = 1156 tests
expected Stage-3.6 chain               = 193 tests
focused Stage-3.6.10                   = 12 tests
```

Package-construction verification completed in the build sandbox:

```text
python compile                                         PASS
pytest collection                                     1156 tests
focused Stage 3.6.10                                  12 passed
Stage-3.5.10 current-head tail assertion              1 passed
Stage-3.4.10 current-head tail assertion              1 passed
```

A broader multi-file regression run produced no observed failure before the sandbox execution window expired, but it did not reach a final pytest summary. Therefore **no full-regression PASS is asserted by package construction**. The complete 1156-test suite remains an explicit responsibility of the target-host acceptance harness.

## Acceptance harness

Run on the target host after restarting the runtime with this package:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_6_10_ACCEPTANCE.ps1
```

The harness refuses to pass unless the active runtime reports:

```text
control_version = stage3.6.10-outcome-acceptance-regression-gate
mission_repository_migration_level = 44
```

It then verifies compile, exact 1156-test collection, complete regression, exact 193-test Stage-3.6 chain, exact 12-test focused closure proof, no migration/store addition, the Stage-3.6 authority matrix, Stage-3.6.9 non-actuating recovery, and Stage-3.6.10 no-new-authority/no-new-I/O/no-new-persistence declarations.

## Definition of closure

Stage 3.6 is considered closed only when the external acceptance harness ends with:

```text
STAGE 3.6.10 ACCEPTANCE: PASS
```

The runtime declaration alone is insufficient. This preserves separation between **runtime behavior** and **release/acceptance evidence**.

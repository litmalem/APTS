# Patch Notes — Stage 3.8.1 Regression Rebase Hotfix 2

## Root cause

Stage 3.8.1 correctly appends:

1. `stage3.7.10-adapt-replan-acceptance-regression-gate`
2. `stage3.8.1-canonical-observability-trace-identity-contract`

as the final two entries of the canonical `supported_controls` chain.

Several predecessor tests were mechanically rebased so their `CONTROL`/`CURRENT_CONTROL` constant pointed to Stage 3.8.1, while their tail-length/index expectations still assumed Stage 3.7.10 was the final element. This produced off-by-one / missing-predecessor assertions only.

## Files changed

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_6_10_outcome_acceptance_regression_gate.py`
- `tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py`
- `tests/test_stage3_7_2_adaptation_trigger_detection_classification.py`
- `tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py`
- `tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py`
- `tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py`

## Verification performed

- Re-run of the exact 9 previously failing test nodes: `9 passed`.
- Stage 3.7.10 focused suite: `12 passed`.
- Stage 3.8.1 focused suite: `12 passed`.

No runtime source, migration, persistence store, trace identity algorithm, API, governance boundary, dispatch behavior, execution behavior, or target actuation behavior is changed by this hotfix.

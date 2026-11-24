# Stage 3.7.8 Hotfix 1 — Regression Baseline Rebase

This hotfix corrects four stale `supported_controls` regression expectations exposed by the authoritative Stage 3.7.8 host acceptance run.

## Host evidence

The Stage 3.7.8 acceptance run successfully passed:

- runtime activation preflight;
- Stage 3.7.8 authority-boundary proof;
- Python compilation;
- canonical inventory: exactly `1322` tests.

The full regression then completed with:

- `1318 passed`;
- `4 failed`;
- no runtime/authority/migration failure.

All four failures were assertions over the `health()["supported_controls"]` ordering.

## Root cause

Stage 3.7.8 correctly appends two controls after Stage 3.7.6:

1. `stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization`
2. `stage3.7.8-atomic-replan-commit-supersession-handoff`

Four historical tests had been rebased to the Stage 3.7.8 current control but still used a Stage 3.7.6-era tail width/order. They therefore skipped Stage 3.7.7 or sliced one element too narrowly.

The runtime `supported_controls` sequence is correct. The defect is test-only.

## Files corrected

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py`
- `tests/test_stage3_7_2_adaptation_trigger_detection_classification.py`

## Exact corrections

- Stage 3.4.10 final tail: add Stage 3.7.7 at index `36`, move Stage 3.7.8 to index `37`, and change unique-tail cardinality from `37` to `38`.
- Stage 3.5.10 tail: add Stage 3.7.7 immediately before Stage 3.7.8 and shift the negative-index assertions by one element.
- Stage 3.7.1 health tail: change `[-7:]` to `[-8:]` and include Stage 3.7.7 before Stage 3.7.8.
- Stage 3.7.2 health tail: change `[-7:]` to `[-8:]` and include Stage 3.7.7 before Stage 3.7.8.

## Runtime impact

None. This hotfix changes tests only.

- no production Python module changed;
- no API route changed;
- no database migration changed;
- no persistence schema changed;
- no control authority changed;
- no service restart required;
- canonical inventory remains exactly `1322` tests.

## Verification in the repair workspace

- canonical collection: `1322 tests collected`;
- the four formerly failing nodes: `4 passed in 2.67s`.

The authoritative full regression must be rerun on the target Windows host through `STAGE3_7_8_ACCEPTANCE.ps1`.

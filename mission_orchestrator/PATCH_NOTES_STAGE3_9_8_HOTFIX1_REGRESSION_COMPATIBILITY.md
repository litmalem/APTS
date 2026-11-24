# Stage 3.9.8 Hotfix 1 — Historical Regression Compatibility

## Trigger

The Windows Stage 3.9.8 acceptance run reached the full historical regression with all prior gates passing. The historical suite then reported exactly three failures and `1542 passed`.

All three failures are stale test expectations for the `supported_controls` chain. The runtime correctly exposes both historical Stage 3.9.7 and current Stage 3.9.8 controls, but three predecessor tests incorrectly collapsed Stage 3.9.7 out of the suffix.

## Failure class A — Stage 3.4.10 exact supported-control suffix

Two assertions in:

`tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`

modeled the end of the chain as:

`... -> Stage 3.9.6 -> CURRENT_CONTROL`

where `CURRENT_CONTROL` is Stage 3.9.8.

The correct canonical chain is:

`... -> Stage 3.9.6 -> Stage 3.9.7 -> Stage 3.9.8`

Hotfix changes:

- preserve `stage3.9.7-adaptation-replanning-e2e-scenario` before Stage 3.9.8 in the exact expected list;
- rebase tail index `56` to Stage 3.9.7;
- place Stage 3.9.8 at tail index `57`;
- rebase unique tail cardinality from `57` to `58`.

## Failure class B — Stage 3.8.1 predecessor-chain suffix cardinality

One assertion in:

`tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`

already listed both Stage 3.9.7 and Stage 3.9.8, but sliced only the last 18 controls. The expected list contains 19 controls beginning at Stage 3.7.10.

Hotfix changes:

- suffix slice `controls[-18:]` -> `controls[-19:]`.

## Scope

Only two historical regression files are changed:

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`

No production/runtime file is changed.

## Invariants preserved

- active control remains `stage3.9.8-restart-replay-recovery-e2e-verification`;
- Stage 3.9.7 remains the immediate historical predecessor of Stage 3.9.8;
- repository migration remains `53`;
- canonical inventory remains `1545`;
- no database migration;
- no new durable store;
- no new recovery authority;
- no new planner, governance, routing, dispatch, execution, or target-actuation authority;
- Stage 3.9.8 restart/replay/recovery semantics are unchanged.

## Local qualification

The two modified historical regression files were executed together after applying Stage 3.9.8:

`24 passed in 11.46s`

The complete 1545-test historical regression was not rerun in the sandbox. Final closure requires rerunning the existing `STAGE3_9_8_ACCEPTANCE.ps1` on the authoritative Windows host.

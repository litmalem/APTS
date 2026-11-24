# Stage 3.9.10 Hotfix 1 — Historical Regression Compatibility

## Trigger

The authoritative Windows Stage 3.9.10 acceptance run passed every pre-final gate:

- runtime activation: PASS;
- final gate contract API: PASS;
- Python compilation: PASS;
- canonical inventory: 1575 tests;
- focused Stage 3.9.10: 15 passed;
- Stage 3.9 canonical E2E qualification chain: 144 passed;
- stage-domain closure gate regression: 101 passed;
- global lineage / governance / recovery / forensic critical regression: 186 passed.

The final full historical regression then completed with exactly one stale assertion:

- 1 failed;
- 1574 passed;
- failing test: `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py::test_12_stage3710_remains_immediate_predecessor_in_supported_control_chain`.

## Root cause

The expected suffix now contains 21 controls:

- Stage 3.7.10;
- Stage 3.8.1 through Stage 3.8.10;
- Stage 3.9.1 through Stage 3.9.10.

However, the historical test still sliced only the last 20 controls:

```python
assert controls[-20:] == [
    "stage3.7.10-adapt-replan-acceptance-regression-gate",
    ...,
    CONTROL,
]
```

After Stage 3.9.10 was appended, `controls[-20:]` correctly begins at Stage 3.8.1, so it cannot equal a 21-element expected list beginning at Stage 3.7.10.

## Fix

Rebase only the historical suffix cardinality:

```diff
- assert controls[-20:] == [
+ assert controls[-21:] == [
```

No production/runtime code is changed.

## Invariants preserved

- active control remains `stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`;
- Stage 3.9.9 remains the immediate predecessor of Stage 3.9.10;
- Stage 3.7.10 remains immediately before Stage 3.8.1 in the canonical historical chain;
- repository migration remains 53;
- canonical inventory remains 1575;
- no database migration;
- no new durable store;
- no new governance, routing, delegation, dispatch, execution, recovery, observation, or forensic authority;
- no external I/O or target actuation is introduced.

## Local qualification

After applying the one-line rebase to the supplied Stage 3.9.10 overlay on the submitted mission snapshot:

```text
27 passed in 7.20s
```

This qualification covered the complete Stage 3.8.1 regression file plus the complete focused Stage 3.9.10 test file.

The authoritative full 1575-test closure must still be rerun on the Windows deployment host using `STAGE3_9_10_ACCEPTANCE.ps1`.

# Stage 3.8.10 Hotfix 1 — Supported-Control Regression Rebase

This hotfix repairs three stale historical regression assertions exposed by the authoritative Windows-host Stage 3.8.10 acceptance run.

## Host evidence

The Stage 3.8.10 runtime and preserved Stage 3.8.9 forensic contract were already active, Python compilation passed, and the canonical inventory remained 1431 tests. Full regression completed with:

- `3 failed, 1428 passed`
- all three failures were historical `supported_controls` order/tail assertions
- no production runtime failure was reported

The failing modules were:

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py` — 2 assertions
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py` — 1 assertion

## Root cause

Stage 3.8.9 is a real preserved control in the current runtime:

`stage3.8.9-forensic-query-evidence-bundle-reconstruction-api`

The three historical closure assertions had been rebased directly from Stage 3.8.8 to the new Stage 3.8.10 current control, accidentally omitting Stage 3.8.9. Therefore the runtime returned the correct canonical sequence, while the tests expected a sequence one item shorter.

## Hotfix scope

Test-only regression rebase:

- Stage 3.4.10 complete supported-control tail now includes Stage 3.8.9 before Stage 3.8.10.
- Stage 3.4.10 terminal indices are shifted from 48/49 items to 49/50 items as appropriate.
- Stage 3.5.10 expected suffix now includes Stage 3.8.9 before Stage 3.8.10.
- Stage 3.5.10 negative tail indices are shifted consistently, with Stage 3.8.9 at `tail[-2]` and Stage 3.8.10 at `tail[-1]`.

No production runtime module, API route, authority boundary, persistence schema, durable store, or database migration changes.

## Local qualification

- Python compilation: PASS
- canonical collection: `1431 tests collected`
- exact three previously failing tests + complete Stage 3.8.10 focused module: `7 passed in 5.54s`

The full canonical regression must be rerun on the authoritative Windows deployment host using `STAGE3_8_10_ACCEPTANCE.ps1`.

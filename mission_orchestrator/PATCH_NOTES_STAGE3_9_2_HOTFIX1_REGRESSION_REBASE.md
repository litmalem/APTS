# PATCH NOTES — Stage 3.9.2 Hotfix 1

## Change

Rebased three stale historical `supported_controls` expectations so the canonical runtime chain preserves Stage 3.9.1 immediately before the active Stage 3.9.2 control.

## Why

The authoritative host completed Stage 3.9.2 preflight/qualification successfully and collected 1458 tests, but the full regression ended with `3 failed, 1455 passed`.

Every failure was a fixed supported-control tail/suffix assertion that omitted:

`stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract`

between Stage 3.8.10 and Stage 3.9.2.

## Files changed

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`

## Runtime impact

None.

- no production code change
- no API change
- no lifecycle or E2E qualification semantic change
- no migration
- no durable store
- no authority expansion
- canonical inventory remains 1458

## Qualification

Local verification after the rebase:

- Python compilation: PASS
- canonical collection: 1458 tests
- exact three previously failing tests: 3 passed
- complete affected + Stage 3.9 predecessor/current modules: 63 passed

Authoritative closure still requires rerunning `STAGE3_9_2_ACCEPTANCE.ps1` on the Windows deployment host.

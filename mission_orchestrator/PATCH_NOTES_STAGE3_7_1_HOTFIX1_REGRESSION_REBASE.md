# PATCH NOTES — Stage 3.7.1 Hotfix 1

## Change

Rebased one stale `supported_controls` expectation in:

`tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`

The expected tail now includes:

`stage3.6.10-outcome-acceptance-regression-gate`

immediately before:

`stage3.7.1-canonical-adaptation-replan-contract-identity`

## Why

The target-host Stage 3.7.1 acceptance completed the canonical suite with `1 failed, 1174 passed`. The only failure was caused by the historical Stage 3.4.10 test omitting the already-active Stage 3.6.10 closure control from one long literal list.

## Runtime impact

None. This hotfix modifies tests only.

- no Python production module changed
- no HTTP/API route changed
- no database migration changed
- no service restart required
- no control authority changed
- test inventory remains exactly `1175`

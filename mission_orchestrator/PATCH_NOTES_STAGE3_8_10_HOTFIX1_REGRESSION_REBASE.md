# PATCH NOTES — Stage 3.8.10 Hotfix 1

## Change

Rebased three stale historical `supported_controls` expectations to preserve Stage 3.8.9 in the canonical control sequence before Stage 3.8.10.

## Why

The authoritative host reported `3 failed, 1428 passed`. The diffs showed that the runtime correctly contained `stage3.8.9-forensic-query-evidence-bundle-reconstruction-api`, while two Stage 3.4.10 assertions and one Stage 3.5.10 assertion expected Stage 3.8.10 immediately after Stage 3.8.8.

## Files changed

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`

## Runtime impact

None.

- production code unchanged
- API routes unchanged
- `control_version` remains `stage3.8.10-observe-reconstruct-acceptance-regression-gate`
- server version remains `APTSMissionOrchestrator/3.8.10`
- repository migration remains 53
- canonical inventory remains 1431
- no new durable store
- no authority expansion

## Qualification

Local sentinel verification after the rebase:

- Python compilation: PASS
- canonical collection: 1431 tests
- exact failed tests + Stage 3.8.10 focused module: 7 passed

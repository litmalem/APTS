# PATCH NOTES — Stage 3.8.4 Hotfix 1

## Change

Rebased stale Stage 3.1–3.7 regression expectations to the active Stage 3.8.4 runtime baseline and repaired historical `supported_controls` window/tail assertions.

## Why

The target-host Stage 3.8.4 acceptance reported `1389 tests collected`, followed by `75 failed, 1314 passed`. The failures consistently showed the runtime returning the correct Stage 3.8.4 control/server versions while older tests still expected Stage 3.8.3. Two complete-tail checks also omitted the Stage 3.8.1–3.8.3 observability lineage controls.

## Runtime impact

None. This hotfix changes regression tests and verification/documentation only.

- no production Python module changed
- no API route changed
- no projection semantics changed
- no database migration changed
- repository migration remains 53
- no new persistence store
- no authority expansion
- canonical test inventory remains 1389

## Qualification

Local verification after the rebase:

- Python compilation: PASS
- canonical collection: 1389 tests
- focused Stage 3.8.1–3.8.4: 33 passed
- full canonical regression: 1389 passed in 1116.30s

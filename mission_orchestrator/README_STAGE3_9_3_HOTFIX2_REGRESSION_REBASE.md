# Stage 3.9.3 Hotfix 2 — Supported-Control Regression Rebase

This hotfix repairs the seven stale historical `supported_controls` assertions exposed by the authoritative Windows-host Stage 3.9.3 full regression.

## Host evidence

Before the full regression, the host passed:

- Stage 3.9.3 runtime activation with migration 53 and no authority expansion;
- live Planning → Task Graph → Dependency qualification, including exact replay idempotency;
- Python compilation;
- canonical collection of 1473 tests;
- 15/15 focused Stage 3.9.3 tests;
- 27/27 Stage 3.9.1 + 3.9.2 predecessor tests;
- 77/77 Stage 3.3.1-3.3.4 planning structural regression.

The complete regression then produced `7 failed, 1466 passed`. Every failure was a historical supported-control suffix/tail assertion that skipped Stage 3.9.2.

## Root cause

This is a regression-baseline defect, not a runtime defect.

The canonical production chain is:

`stage3.8.10 -> stage3.9.1 -> stage3.9.2 -> stage3.9.3`

The seven failing tests expected Stage 3.9.1 to be followed directly by Stage 3.9.3. Their fixed suffix lengths therefore also started one element too late.

## Exact correction

Each affected assertion now includes:

`stage3.9.2-intake-lifecycle-e2e-segment-qualification`

before:

`stage3.9.3-planning-task-graph-dependency-verification`

Corresponding negative-slice lengths were increased by one. In the Stage 3.5.10 historical tail test, all explicit negative indexes were shifted consistently so the existing chain invariants remain exact.

## Scope

Test-only. No runtime source, API route, repository schema, persistence store, governance/routing/delegation/dispatch/execution authority, or Stage 3.9.3 qualification semantics are changed.

## Verification

Run:

```powershell
.\STAGE3_9_3_HOTFIX2_VERIFY.ps1
```

Then run the authoritative gate again:

```powershell
.\STAGE3_9_3_ACCEPTANCE.ps1
```

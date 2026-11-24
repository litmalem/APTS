# Stage 3.9.7 Hotfix 1 — Regression Compatibility

Apply this overlay **over the existing Stage 3.9.7 deployment**.

The hotfix repairs two issues found only by the final historical regression:

1. stale predecessor tests that omitted Stage 3.9.6 from the `supported_controls` suffix after Stage 3.9.7 activation;
2. a Stage 3.8 observability compatibility regression where the live projection used the strict plan-version-history API and rejected otherwise valid missions with no plan-version rows.

No database migration is added. Repository migration remains `53`, canonical inventory remains `1531`, and the active control remains:

`stage3.9.7-adaptation-replanning-e2e-scenario`

After applying the overlay, rerun:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_7_ACCEPTANCE.ps1
```

Expected pre-full-regression gates remain:

- focused Stage 3.9.7: 16 tests;
- Stage 3.9 E2E predecessor chain: 100 tests;
- adaptation/replanning authority regression: 200 tests;
- canonical inventory: 1531 tests.

Stage 3.9.7 closes only when the final full historical regression reports zero failures.

# Stage 3.9.6 Hotfix 1 — Regression Rebase

Apply this package **over the existing Stage 3.9.6 deployment**.

The hotfix repairs stale historical `supported_controls` assertions that omitted:

`stage3.9.5-dispatch-execution-evidence-continuity`

between Stage 3.9.4 and Stage 3.9.6.

This is a test-only regression rebase. Runtime code, mission repository migration level, authority boundaries, Stage 3.9.6 semantics, and database state are unchanged.

After deployment run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_6_ACCEPTANCE.ps1
```

Expected canonical inventory remains `1515 tests`.

A successful host run must complete the full historical regression with zero failures and then report Stage 3.9.6 acceptance PASS.

# Stage 3.9.4 Hotfix 1 — Regression Rebase

Apply this package over the existing Stage 3.9.4 deployment.

The hotfix repairs stale predecessor regression assertions that omitted Stage 3.9.3 from `supported_controls` ordering. Runtime code and database state are unchanged.

After deployment run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_4_ACCEPTANCE.ps1
```

Expected canonical inventory remains 1485 tests. A successful host run must end with the full regression PASS and Stage 3.9.4 acceptance PASS.

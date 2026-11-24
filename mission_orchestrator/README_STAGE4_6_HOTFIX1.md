# Stage 4.6 HOTFIX1 — Windows Local HTTP Regression Stability

This hotfix addresses an intermittent Windows localhost socket abort observed only during the
combined Stage 4.1→4.6 pytest regression. It does not change Stage-4.6 production runtime.

Apply from the project root (`D:\mission_orchestrator`) by copying the hotfix tree over the
existing files, then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE4_6_HOTFIX1_VERIFY.ps1
.\STAGE4_6_ACCEPTANCE.ps1
```

Expected hotfix verification:

```text
Focused Stage 4.6             26 passed
Stage 4.1 -> 4.6             122 passed
Critical predecessor chain   181 passed
```

The final authority remains `STAGE4_6_ACCEPTANCE.ps1`, including the full historical
1697-test regression.

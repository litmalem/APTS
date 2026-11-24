# Stage 3.9.10 Hotfix 1 — Historical Regression Compatibility

Apply this overlay **over the existing Stage 3.9.10 deployment** in `D:\mission_orchestrator`.

The host acceptance evidence shows the Stage 3.9.10 runtime and all targeted closure gates are healthy. The only final-regression failure is a stale suffix-cardinality assertion in the Stage 3.8.1 historical test.

The hotfix changes exactly one test expression:

```diff
- controls[-20:]
+ controls[-21:]
```

The expected control list already contains the correct canonical 21-element suffix from Stage 3.7.10 through Stage 3.9.10. The runtime control chain is therefore not changed by this hotfix.

## Quick verification

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_10_HOTFIX1_VERIFY.ps1
```

Expected result:

```text
[PASS] Stage 3.9.10 Hotfix 1 regression compatibility
```

## Final closure

Then rerun the authoritative acceptance gate:

```powershell
.\STAGE3_9_10_ACCEPTANCE.ps1
```

Stage 3 closes only when the final full historical regression reports all `1575 passed` with zero failures.

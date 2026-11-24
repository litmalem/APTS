# Stage 3.9.3 Hotfix 1 — Acceptance Client Import Bootstrap

## Problem observed on authoritative Windows host

`STAGE3_9_3_ACCEPTANCE.ps1` passed the runtime activation gate, then failed while launching:

```text
python .\run\stage3_9_3_acceptance_client.py
```

with:

```text
ModuleNotFoundError: No module named 'mission_orchestrator'
```

## Root cause

Direct script execution makes Python use the script directory (`run`) as `sys.path[0]`. The repository root is therefore not guaranteed to be on the import path, so the sibling `mission_orchestrator` package cannot be resolved.

## Fix

`run/stage3_9_3_acceptance_client.py` now derives its repository root from `__file__` and prepends that root to `sys.path` before importing any `mission_orchestrator.*` module.

The fix is local to the acceptance harness. It does **not** modify:

- runtime authority;
- Stage 3.9.3 qualification semantics;
- HTTP contracts;
- persistence schema;
- repository migration level (remains 53);
- test inventory expectation (remains 1473).

## Re-run

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_3_ACCEPTANCE.ps1
```

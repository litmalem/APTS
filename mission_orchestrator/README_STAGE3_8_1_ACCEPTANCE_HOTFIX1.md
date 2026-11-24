# Stage 3.8.1 Acceptance Hotfix 1 — Windows Python Compile Portability

## Problem

`STAGE3_8_1_ACCEPTANCE.ps1` used:

```powershell
& python -m py_compile mission_orchestrator/*.py run/*.py
```

PowerShell passes those wildcard strings to Python rather than expanding them for `py_compile`. On Windows this causes Python to attempt to open the literal path `mission_orchestrator/*.py`, resulting in `[Errno 22] Invalid argument`.

## Fix

The compile gate now uses Python's directory-aware compiler:

```powershell
& python -m compileall -q mission_orchestrator run tests
```

This preserves the intent of the acceptance gate while making it portable on the target Windows host.

## Scope

- Acceptance harness only.
- No runtime source change.
- No schema change.
- No database migration.
- Repository migration remains `53`.
- `control_version` remains `stage3.8.1-canonical-observability-trace-identity-contract`.

## Apply

Replace the repository-root `STAGE3_8_1_ACCEPTANCE.ps1` with the hotfixed file, then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_8_1_ACCEPTANCE.ps1
```

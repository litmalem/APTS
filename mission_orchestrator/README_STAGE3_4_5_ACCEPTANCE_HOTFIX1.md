# Stage 3.4.5 Acceptance Hotfix 1

## Problem

Windows PowerShell does not expand wildcard path arguments passed to native executables in the same way a POSIX shell does. The original acceptance harness invoked:

```powershell
python -m pytest -q tests\test_stage3_1*.py
python -m pytest -q tests\test_stage3_2*.py
```

Pytest therefore received the literal wildcard path and returned `file or directory not found`.

## Fix

The harness now resolves matching test files in PowerShell with `Get-ChildItem`, verifies that at least one file was discovered, and passes the resolved path array to pytest.

No Mission Orchestrator runtime, repository, migration, Governance contract, or Stage-3.4.5 implementation code is changed by this hotfix.

## Apply

Copy `STAGE3_4_5_ACCEPTANCE.ps1` over the file in `D:\mission_orchestrator`, then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_4_5_ACCEPTANCE.ps1
```

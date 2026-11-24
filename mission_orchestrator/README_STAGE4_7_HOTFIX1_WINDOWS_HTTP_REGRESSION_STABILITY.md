# Stage 4.7 HOTFIX1 — Windows HTTP Regression Stability

This hotfix addresses Windows-only localhost HTTP transport flakiness observed during the
Stage 4.7 critical predecessor regression.

## Install

Overlay the hotfix at the repository root (`D:\mission_orchestrator`) so the `tests` directory
is merged with the existing source tree.

No database migration or runtime restart is required by this hotfix because production source
and persistence schemas are unchanged.

## Verify the previously failing test

```powershell
cd D:\mission_orchestrator
python -m pytest -q `
  tests/test_stage4_3_pentest_mission_task_contract.py::test_17_http_stage43_health_contract_create_get_list_and_execution_negative_boundary
```

Expected:

```text
1 passed
```

## Re-run Stage 4.7 acceptance

```powershell
cd D:\mission_orchestrator

Set-ExecutionPolicy `
    -Scope Process `
    -ExecutionPolicy Bypass `
    -Force

.\STAGE4_7_ACCEPTANCE.ps1
```

The Stage 4.7 acceptance script remains unchanged and remains the final authority. Expected
inventory is still `1724 tests collected`.

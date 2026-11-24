# Stage 3.8.1 Regression Rebase Hotfix 2

This hotfix repairs stale `supported_controls` ordering assertions in predecessor regression tests after activation of Stage 3.8.1.

## Scope

Runtime implementation is unchanged. Database schema is unchanged. Repository migration remains 53. The Stage 3.8.1 trace contract is unchanged.

The full regression run reported 1359 passed and 9 failed. Every failure was an assertion in an older test that had been rebased to the new active `control_version` but did not preserve Stage 3.7.10 immediately before Stage 3.8.1 in `supported_controls`.

Eight test files are updated because two failures were in the Stage 3.4.10 test file.

## Apply

Extract this archive at the repository root (`D:\mission_orchestrator`) and allow the eight `tests/...` files to be replaced. Keep the Acceptance Hotfix 1 version of `STAGE3_8_1_ACCEPTANCE.ps1`; Hotfix 2 does not replace that script.

## Fast verification

Run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_8_1_HOTFIX2_VERIFY.ps1
```

Expected terminal result:

```text
STAGE 3.8.1 REGRESSION REBASE HOTFIX 2: PASS
```

Then run the authoritative acceptance:

```powershell
.\STAGE3_8_1_ACCEPTANCE.ps1
```

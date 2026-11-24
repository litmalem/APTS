# Stage 2.9.8 H1 — Acceptance Runner Hotfix

This hotfix corrects two defects in the Stage 2.9.8 PowerShell acceptance runner. It does not modify VulnDesk runtime code, governance_service code, or database schema.

## Fixed defects

1. **Read-only semantic probe failure**
   - Original runner assumed `lineage.mission_id` always exists.
   - The mission-lineage projection used by the current runtime does not guarantee that property at that location.
   - H1 resolves mission identity defensively from `lineage.mission_id`, then `lineage.identity.mission_id`, and finally the canonical `-MissionId` argument.
   - The same defensive handling is used for integrity/task semantic views.

2. **Windows PowerShell 5.1 finalization failure**
   - Original runner used `@($script:Checks)` on a `System.Collections.Generic.List[object]` while constructing the final ordered summary.
   - Windows PowerShell 5.1 may raise `Argument types do not match` for this binder path.
   - H1 materializes the list through the PowerShell pipeline before serializing `99_acceptance_summary.json`.

## Replay support

H1 can complete the already-created mission without creating a second mission. With `-ReuseExistingMission`, it rehydrates and validates:

- `21_scope_response.json`
- `23_mission_start_response.json`

from the existing evidence directory. It also reuses the recovered ScopeContract ID for the governed task binding check.

## Recommended command for the failed run

```powershell
cd D:\vulndesk
.\.venv\Scripts\activate

Set-ExecutionPolicy `
    -Scope Process `
    -ExecutionPolicy Bypass `
    -Force

Copy-Item .\STAGE2_9_8_E2E_ACCEPTANCE_H1.ps1 .\STAGE2_9_8_E2E_ACCEPTANCE.ps1 -Force

.\STAGE2_9_8_E2E_ACCEPTANCE.ps1 `
    -MissionId "mission-stage298-e2e-20260902-022733" `
    -ReuseExistingMission
```

Do not use `-SkipRegression` for the formal closure rerun unless you intentionally want a shorter diagnostic replay. Running the full command above gives a new complete acceptance summary while preserving the original mission and evidence folder.

## Expected closure

```text
STATUS                 : PASS
MANDATORY_FAIL         : 0
[PASS] TAHAP 2.9.8 END-TO-END ACCEPTANCE CLOSED.
```

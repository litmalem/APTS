# Stage 3.3.3 Acceptance Hotfix — Canonical Validation Error Code

## Scope

Acceptance-artifact-only hotfix. No Mission Orchestrator runtime source, database schema, migration level, task-decomposition semantics, Governance authority, planner boundary, or target-execution capability changes.

## Root cause

Gate [7] of `STAGE3_3_3_ACCEPTANCE.ps1` correctly injects the forbidden Stage-3.3.4 field `dependencies` into a Stage-3.3.3 planned task. The runtime validator correctly raises `MissionValidationError` before persistence.

The canonical HTTP error mapping already established by the Mission Orchestrator maps `MissionValidationError` to:

- HTTP `400`
- code `MISSION_CONTRACT_INVALID`

The original Stage-3.3.3 acceptance script incorrectly expected `MISSION_VALIDATION_ERROR`, a code that is not part of the canonical API error contract. Stage 3.3.1 and Stage 3.3.2 acceptance scripts already use `MISSION_CONTRACT_INVALID` for equivalent contract-surface validation failures.

## Correction

Gate [7] now requires:

```powershell
$invalidFailure.status -eq 400
$invalidFailure.body.code -eq "MISSION_CONTRACT_INVALID"
```

This preserves the intended invariant: dependency-bearing Stage-3.3.3 tasks fail closed before Stage 3.3.4 graph materialization.

## Runtime impact

None.

- no Python source changes;
- no database migration;
- migration level remains `11`;
- regression baseline remains `315 passed`;
- no planner invocation;
- no dependency graph materialization;
- no Governance authorization change;
- no target dispatch or actuation.

## Install

Replace only:

`D:\mission_orchestrator\STAGE3_3_3_ACCEPTANCE.ps1`

No service restart is required because runtime code is unchanged.

Then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_3_ACCEPTANCE.ps1
```

Expected final result:

```text
STAGE 3.3.3 ACCEPTANCE: PASS
```

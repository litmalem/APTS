# Patch Notes — Stage 3.3.1 Canonical Plan Contract & Identity

## Added

- `mission_orchestrator/mission_plan.py`
  - canonical Plan schema and constants;
  - request normalization and request fingerprinting;
  - stable `mplan-*` identity generation;
  - immutable Plan contract builder;
  - SHA-256 integrity verification;
  - static Plan-contract discovery definition.
- `migrations/009_stage3_3_1_canonical_plan_contract_identity.sql`
  - durable `mission_plans` store;
  - repository migration level `9`.
- `MISSION_PLAN_CONTRACT_REGISTERED` canonical Mission event type.
- Plan registration/read/discovery APIs.
- `mission_plan_version` in the canonical Mission version vector.
- Plan store in repository persistence/reconstruction and integrity checks.
- `tests/test_stage3_3_1_canonical_plan_contract_identity.py` with 13 Stage-3.3.1 tests.
- `STAGE3_3_1_ACCEPTANCE.ps1` and Stage-3.3.1 release documentation.

## Changed

- Current control advances to `stage3.3.1-canonical-plan-contract-identity`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.3.1`.
- Repository migration level advances from `8` to `9`.
- Repository store manifest adds `mission_plans`.
- Repository core signature includes canonical Plan state.
- Historical regression assertions are advanced to recognize Stage 3.3.1 as the current runtime while preserving Stage 3.2.10 as the closed lifecycle baseline.
- Package description advances through Stage 3.3.1.

## Preserved

- Stage 3.1 canonical Mission identity/state/scope/governance/event contracts.
- Stage 3.2 lifecycle topology, guards, activation, waiting, pause/resume/replan, terminal semantics, cleanup/completion, automation, and closure gate.
- `EXTERNAL_APTS_GSS` as sole Governance/authorization authority.
- No planner invocation.
- No task decomposition/materialization.
- No Plan revision.
- No target-action dispatch or target actuation.
- No interpretation of workflow readiness as authorization.

## Canonical invariants

- `PLAN != AUTHORIZATION`
- `TASK != DISPATCH`
- `READINESS != PERMISSION`
- `PLANNER != GOVERNANCE`

## Validation

- Python compile: PASS.
- Focused Stage-3.3.1 tests: **13 passed**.
- Full Stage-3 regression: **280 passed**.
- Live acceptance: `STAGE3_3_1_ACCEPTANCE.ps1`.

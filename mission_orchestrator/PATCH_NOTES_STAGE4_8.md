# Patch Notes — Stage 4.8

## Added

- `pentest_subsystem/governance_contract.py`
  - canonical Stage-4.8 control contract
  - canonical evaluation envelope
  - deterministic fail-closed scope/RoE evaluator
  - canonical eligibility decision and integrity binding
- `pentest_subsystem/governance_repository.py`
  - migration level 6
  - append-only decision audit/replay store
  - tamper verification and idempotent replay
- `pentest_subsystem/governance_service.py`
  - runtime activation and health projection
  - scope/RoE evaluation/query API service
- `pentest_migrations/006_stage4_8_governance_scope_roe_enforcement.sql`
- `tests/test_stage4_8_governance_scope_roe_enforcement.py`
- `STAGE4_8_ACCEPTANCE.ps1`

## Changed

- `pentest_subsystem/api_service.py`
  - added `PentestSubsystemStage48Handler`
  - current active server now Stage 4.8
  - historical Stage-4.1…4.7 handlers retained
- `run/pentest_subsystem.py`
  - runtime description advanced to Stage 4.8
- `pentest_subsystem/capability_repository.py`
  - forward-compatible migration handling for Stage-4.8 subclass without weakening Stage-4.7 direct repository checks

## Invariants

1. Local eligibility is not authorization.
2. Any failed required scope/RoE rule produces `INELIGIBLE`.
3. Human-approval-required action produces `REVIEW_REQUIRED`, never local ALLOW.
4. Evaluation cannot invoke tools or perform target I/O.
5. Execution intake remains disabled.

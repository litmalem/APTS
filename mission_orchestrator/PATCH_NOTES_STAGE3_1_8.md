# Patch Notes — Stage 3.1.8 Canonical Mission API & Validation Layer

## Summary

This patch advances `mission_orchestrator` from Stage 3.1.7 Mission Persistence & Repository Model to **Stage 3.1.8 Canonical Mission API & Validation Layer**.

The patch stabilizes the external canonical mission read contract and adds a stateless composite preflight validator over the already accepted Stage-3.1 mission and Scope/RoE/Constraint schemas.

## Added

### `mission_orchestrator/mission_validation.py`

Defines:

- `apts-canonical-mission-api-v1`;
- `apts-canonical-mission-validation-v1`;
- ordered `SCHEMA -> SEMANTIC -> SCOPE -> CONSTRAINTS` validation;
- supported canonical subsystem admission (`CTI`, `PENTEST`);
- positive-scope admission;
- mission-duration vs Scope-constraint alignment;
- deterministic mission/scope request fingerprints;
- explicit zero-side-effect validation result.

### Validation pipeline error

New exception:

- `MissionValidationPipelineError`

New HTTP error contract:

- `400 MISSION_VALIDATION_FAILED`
- phase and check identifier included in the response.

### Validation API

New endpoint:

- `POST /api/missions/validate`

It is preflight-only and performs no persistence, Governance/CTI query, planning, dispatch, or target action.

### Canonical contract projection

New endpoint:

- `GET /api/missions/{mission_id}/canonical-contract`

It binds the local identity/envelope/state/current-Scope view into one canonical API response. It is `IDENTITY_STATE_ONLY` before Scope binding and `SCOPE_BOUND` after a current Scope snapshot exists.

### Health metadata

Health now advertises the Stage-3.1.8 API/validation schema, pipeline, preflight mode, and preserved external-authority boundary.

### Regression coverage

Stage-3.1.8 tests prove:

- current control and prior Stage-3.1.7 support;
- valid four-layer preflight with zero persistence/authority calls;
- schema failure attribution;
- semantic failure attribution;
- scope failure attribution;
- constraint failure attribution;
- cross-contract duration-budget rejection;
- deterministic validation fingerprints;
- local canonical contract projection before/after Scope binding.

Current regression result: **91 passed**.

## Preserved

- Stage-3.1.1 canonical global mission identity/envelope.
- Stage-3.1.2 canonical state machine and state CAS.
- Stage-3.1.3 immutable/versioned Scope/RoE/Constraint contract.
- Stage-3.1.4 external aptsGSS Governance authority.
- Stage-3.1.5 governed routing boundary.
- Stage-3.1.6 version-vector concurrency and command journal.
- Stage-3.1.7 durable repository/reconstruction model and migration level 7.
- `dispatch_enabled=false`.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.

## Database

No Stage-3.1.8 migration is required. Existing SQLite/MariaDB/MySQL data remains unchanged.

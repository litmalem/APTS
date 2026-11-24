# Patch Notes — Stage 3.2.1 Mission Lifecycle Command Contract

## Added

- `mission_orchestrator/mission_lifecycle.py` with the canonical lifecycle command schema and deterministic command-to-state mapping.
- Dedicated lifecycle command API:
  - `GET /api/missions/{mission_id}/lifecycle-command-contract`
  - `POST /api/missions/{mission_id}/lifecycle/commands`
- Guarded generic command operation `LIFECYCLE_COMMAND` layered on the existing Stage-3.1.6 version-vector/idempotency command journal.
- Lifecycle command vocabulary:
  - `BIND_PIP`
  - `START_PLANNING`
  - `START`
  - `WAIT_FOR_EVIDENCE`
  - `WAIT_FOR_APPROVAL`
  - `PAUSE`
  - `RESUME`
  - `REPLAN`
  - `BEGIN_CLEANUP`
  - `COMPLETE`
  - `ABORT`
  - `FAIL`
  - `EXPIRE`
- Explicit `RESUME` target contract restricted to canonical pre-existing resume targets.
- Fourteen Stage-3.2.1 tests covering schema validation, deterministic mapping, version guards, idempotency, replay, topology enforcement, terminal immutability, generic-API bypass protection, command journal, and lineage.
- `STAGE3_2_1_ACCEPTANCE.ps1` for local regression and live contract probes.

## Changed

- Current Mission Orchestrator `control_version` advances to `stage3.2.1-mission-lifecycle-command-contract`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.1`.
- `SUPPORTED_COMMAND_OPERATIONS` adds `LIFECYCLE_COMMAND`.
- Existing Stage-3.1 regression assertions now recognize Stage 3.2.1 as the current control while retaining Stage 3.1.10 in `supported_controls`.

## Preserved

- Repository migration level **8**; no Stage-3.2.1 migration.
- Existing Stage-3.1 canonical mission identity, state, Scope/RoE/Constraint, Governance binding, routing, versioning, persistence, API validation, event, lineage, and acceptance-gate contracts.
- Stage-3.1.2 remains the canonical state-topology legality boundary.
- Stage-3.1.6 remains the durable version-vector/idempotency command gate.
- Stage-3.1.9 remains the mission event/lineage foundation.
- aptsGSS remains the sole policy/authorization/approval/revocation/emergency-stop authority.
- `dispatch_enabled=false` for target-action execution.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.

## Deliberately not added

- No Stage-3.2.2 lifecycle prerequisite/guard matrix yet.
- No PIP artifact verification/binding semantics beyond the lifecycle intent `BIND_PIP`; that belongs to the subsequent lifecycle stages.
- No approval decision logic.
- No evidence-completion gate.
- No planner.
- No target-action dispatch or actuation.
- No source changes to aptsGSS or VulnDesk.
- No new durable store or schema migration.

## Validation

- Python compile: PASS.
- Full regression: **125 passed** (111 previous baseline + 14 Stage-3.2.1 tests).

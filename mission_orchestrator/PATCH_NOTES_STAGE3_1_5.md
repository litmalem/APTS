# Patch Notes — Stage 3.1.5 Governed Task Routing

## Summary

This patch advances `mission_orchestrator` from Stage 3.1.4 Governance/Authorization Binding to Stage 3.1.5 Governed Task Routing.

It adds a fail-closed, immutable high-level subsystem routing contract and the first real downstream adapter for VulnDesk CTI while preserving the authority separation established in Stages 3.1.1–3.1.4.

## Important roadmap clarification

The repository's `Canonical Mission State Model` is Stage 3.1.2. Stage 3.1.5 is `Governed Task Routing` and consumes the Stage-3.1.2 state model as its lifecycle gate.

## Added

### `mission_orchestrator/task_routing.py`

New Stage-3.1.5 domain model and CTI transport adapter:

- immutable governed routing task contract;
- SHA-256 integrity verification;
- strict task request normalization;
- capability-derived destination routing;
- CTI route mapping (`CTI-*` -> `/api/cti/missions/start`);
- protected canonical lineage injection into CTI payloads;
- fail-closed CTI HTTP client;
- response-loss readback support.

### Repository persistence

New durable tables and repository methods for:

- `mission_routed_tasks`;
- `mission_task_dispatch_attempts`;
- task idempotency;
- task status transitions;
- dispatch-attempt history and recovery provenance.

### API

New routes:

- `POST /api/missions/{mission_id}/routing-tasks`
- `GET /api/missions/{mission_id}/routing-tasks`
- `GET /api/missions/{mission_id}/routing-tasks/{task_id}`
- `POST /api/missions/{mission_id}/routing-tasks/{task_id}/dispatch`
- `GET /api/missions/{mission_id}/routing-projection`

New error contracts:

- `MISSION_TASK_CONFLICT`
- `MISSION_TASK_NOT_FOUND`
- `MISSION_TASK_ROUTING_FAIL_CLOSED`
- `MISSION_SUBSYSTEM_UNAVAILABLE`
- `MISSION_SUBSYSTEM_PROTOCOL_ERROR`

### Migration

Added:

`migrations/005_stage3_1_5_governed_task_routing.sql`

### Tests

Added:

`tests/test_stage3_1_5_governed_task_routing.py`

The full test baseline is now:

`61 passed`

## Changed

### `mission_orchestrator/service.py`

- control version advanced to `stage3.1.5-governed-task-routing`;
- injected CTI subsystem client;
- added governed task creation/read/dispatch operations;
- added read-only routing-state projection;
- health contract extended for Stage-3.1.5 routing;
- target-action dispatch remains disabled.

### `mission_orchestrator/repository.py`

- SQLite/MySQL schema support for routed tasks and dispatch attempts;
- durable CRUD/read-model methods for Stage 3.1.5.

### `mission_orchestrator/api_service.py`

- Stage-3.1.5 HTTP routes and error mappings;
- runtime banner updated.

### `mission_orchestrator/errors.py`

- Stage-3.1.5 routing and subsystem error types.

### `tests/test_stage3_1_4_governance_authorization_binding.py`

The Stage-3.1.4 health assertion now verifies that the 3.1.4 control remains present in `supported_controls`, instead of requiring the current control version to stay pinned to 3.1.4.

## Security / authority invariants preserved

- APTS-MO01 does not become PolicyDecision authority.
- aptsGSS/GOV-PLANE remains authoritative for ALLOW/DENY/REVIEW, approval, revocation, hard-deny, and emergency stop.
- Routing accepts only `NOT_REQUIRED_INTERNAL` non-actuating capabilities.
- `REQUIRED` target capabilities cannot be dispatched through Stage 3.1.5.
- Route destination is derived from immutable capability binding; the caller cannot choose an arbitrary URL/component.
- Destination must appear in immutable `required_subsystems`.
- Current scope and Governance binding must still exactly match the task before dispatch.
- CTI outage is fail-closed.
- Cross-subsystem projection is read-only and cannot rewrite canonical mission state.
- `dispatch_enabled=false`, `target_action_dispatch_enabled=false`, and `target_actuation=false` remain in the health contract.

## Runtime dependencies

Stage 3.1.5 acceptance requires these existing services:

- Mission Orchestrator: `http://127.0.0.1:8780`
- aptsGSS Governance: `http://127.0.0.1:8770`
- VulnDesk CTI: `http://127.0.0.1:8765`

No Stage-3.1.5 source patch is required in aptsGSS or VulnDesk.

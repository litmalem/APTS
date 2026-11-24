# Patch Notes — Stage 3.1.6 Mission Versioning & Concurrency Mode

## Summary

This patch advances `mission_orchestrator` from Stage 3.1.5 Governed Task Routing to Stage 3.1.6 Mission Versioning & Concurrency Mode.

It addresses four failure classes called out by the Stage-3.1.6 roadmap:

1. stale write;
2. duplicate command;
3. concurrent transition; and
4. cross-resource race condition.

## Added

### `mission_orchestrator/mission_versioning.py`

- canonical version-vector schema and SHA-256 domain;
- version-vector core builder;
- routed-task set fingerprint;
- strict command request normalization;
- command request fingerprint;
- supported guarded operation registry;
- Stage-3.1.6 concurrency-mode constant.

### Mission version-vector service

The service composes the exact current local version domains plus observable downstream/authority versions:

- mission envelope;
- canonical state;
- Scope/RoE/Constraint contract;
- Governance binding and bound Governance scope;
- latest authoritative PolicyDecision version, when present;
- CTI local state/plan versions after subsystem dispatch;
- routed-task set revision fingerprint.

External versions are observed, not owned.

### Mission command gate

A new durable command journal plus guarded execution path provides:

- `command_id` deduplication;
- `(mission_id, idempotency_key)` deduplication;
- canonical request conflict detection;
- stale `expected_version_sha256` rejection;
- native expected-version agreement checks;
- deterministic completed-command replay;
- before/after version-vector evidence;
- failed/stale command audit without mission mutation;
- shared re-entrant serialization across guarded and legacy mutable service entry points within one Mission Orchestrator runtime.

### New API routes

- `GET /api/missions/{mission_id}/version-vector`
- `POST /api/missions/{mission_id}/commands`
- `GET /api/missions/{mission_id}/commands`
- `GET /api/missions/{mission_id}/commands/{command_id}`

### New error mappings

- `409 MISSION_VERSION_CONFLICT`
- `409 MISSION_COMMAND_CONFLICT`
- `404 MISSION_COMMAND_NOT_FOUND`
- `503 MISSION_VERSION_OBSERVATION_UNAVAILABLE`

### Persistence

New table:

- `mission_command_journal`

SQLite creates it automatically at repository startup. MariaDB/MySQL uses migration `006_stage3_1_6_mission_versioning_concurrency.sql`.

## Preserved

- Stage-3.1.2 `expected_state_version` CAS remains authoritative for canonical state writes.
- Stage-3.1.3 `expected_contract_version` remains authoritative for Scope/RoE revisions.
- Stage-3.1.4 `expected_binding_version` remains authoritative for Governance binding revisions.
- Stage-3.1.4 distributed idempotency/recovery remains unchanged for Governance calls.
- Stage-3.1.5 routing idempotency/response-loss recovery remains unchanged.
- aptsGSS policy/approval/revocation/emergency authority is unchanged.
- CTI local state/plan authority is unchanged.
- target-action dispatch and target actuation remain disabled in Mission Orchestrator.

## Regression coverage

Stage-3.1.6 tests prove:

- stable multi-domain vector construction;
- exact tracking of `state_version`, scope version, binding version, CTI `state_version`, and CTI `plan_version`;
- policy version enters the vector after an authoritative PolicyDecision binding;
- duplicate command returns the original result exactly once;
- conflicting duplicate command is rejected;
- stale vector is rejected without mutation;
- two concurrent transitions from one vector produce exactly one winner;
- downstream CTI plan drift invalidates an old vector;
- Stage-3.1.6 health plus authority boundary.

Current regression result: **70 passed**.

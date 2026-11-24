# Stage 3.1.7 — Mission Persistence & Repository Model

## Purpose

Stage 3.1.7 formalizes **durable mission persistence** as infrastructure owned by the Global Mission Orchestrator (`APTS-MO01`) and makes the repository model observable and verifiable.

Stages 3.1.1–3.1.6 already persisted individual mission artifacts. Stage 3.1.7 does not replace those contracts or introduce a second source of truth. It adds a canonical repository contract over the existing normalized stores so that a mission can be reconstructed from durable storage after process restart and checked for internal consistency.

The authority boundary remains unchanged:

- APTS-MO01 owns canonical global mission identity, envelope, lifecycle state, Scope/RoE/Constraint snapshots, Governance bindings, high-level routing contracts, and the local command journal.
- `aptsGSS / GOV-PLANE` remains authoritative for Governance scope/policy decisions, approval, revocation, hard-deny, and emergency-stop semantics.
- VulnDesk/CTI remains authoritative for its subsystem-local mission `state_version` and `plan_version`.
- Persistence is infrastructure, not an agent and not an authorization authority.

## Repository contract

Stage 3.1.7 introduces repository schema metadata:

- `schema_version = apts-mission-repository-v1`
- `migration_level = 7`
- `storage_model = NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS`
- source of truth: `MISSION_ORCHESTRATOR_DATABASE`
- recovery mode: `DURABLE_RECONSTRUCTION_NO_IN_MEMORY_SOURCE_OF_TRUTH`
- integrity mode: `CANONICAL_HASH_AND_RELATIONAL_HEAD_CHAIN_VERIFICATION`

The repository retains the existing normalized stores:

1. `global_missions`
2. `mission_envelopes`
3. `mission_states`
4. `mission_state_transitions`
5. `mission_scope_contract_heads`
6. `mission_scope_contract_versions`
7. `mission_governance_binding_heads`
8. `mission_governance_binding_versions`
9. `mission_governance_binding_operations`
10. `mission_authorization_operations`
11. `mission_authorization_bindings`
12. `mission_routed_tasks`
13. `mission_task_dispatch_attempts`
14. `mission_command_journal`

Stage 3.1.7 adds only repository metadata; it does not duplicate Governance or CTI authority tables.

## Persistence manifest

`GET /api/missions/{mission_id}/repository`

returns a local-only deterministic persistence projection with:

- repository metadata and storage driver;
- durable record counts;
- current state projection;
- append-only transition ledger references;
- Scope/RoE/Constraint version store and current head;
- Governance binding version store, operation journal, and current head;
- authorization operation/binding references;
- routed task and dispatch-attempt references;
- Stage-3.1.6 command-journal references;
- integrity checks;
- `repository_sha256`;
- `persistence_manifest` using schema `apts-mission-persistence-manifest-v1`.

`reconstructed_at` is deliberately excluded from the manifest hash. Therefore repeated reconstruction of unchanged durable state produces the same `repository_sha256`, including after a Mission Orchestrator process restart.

Live Governance and CTI reads are deliberately excluded from repository reconstruction. Stage 3.1.7 proves **local durable recovery**, not ownership of external state.

## Integrity checks

Repository reconstruction fails closed if the local durable model is inconsistent. Checks include:

- repository schema metadata/migration level;
- immutable mission-envelope SHA-256 and identity binding;
- reconstruction of the current canonical state from the append-only transition ledger;
- legal/contiguous state-version transitions and current-state head agreement;
- Scope contract canonical hashes, contiguous versions, and current-head pointer/hash agreement;
- Governance binding canonical hashes, contiguous versions, bound mission-scope references, and current-head agreement;
- authorization-binding canonical hashes and references to persisted binding/scope versions;
- routed-task canonical hashes and dispatch-attempt sequencing;
- persisted Stage-3.1.6 version-vector integrity in the command journal;
- durable database record counts matching the reconstructed object sets.

Integrity failure raises `MISSION_REPOSITORY_INTEGRITY_ERROR` and maps to HTTP 503. The service does not silently repair or reinterpret corrupted canonical records.

## Recovery invariant

A fresh `MissionRepository` + `CanonicalMissionService` instance opened over the same durable database must reconstruct the same mission state and the same `repository_sha256` without cloning the previous runtime object or relying on in-memory state.

This is covered by Stage-3.1.7 regression tests for SQLite local acceptance. MariaDB/MySQL uses the same repository contract through migration 007.

## API addition

- `GET /api/missions/{mission_id}/repository`

Existing Stage-3.1.1 through Stage-3.1.6 APIs remain available.

## Database change

New table:

- `mission_repository_metadata`

SQLite creates/updates the singleton metadata row automatically on repository startup. MariaDB/MySQL uses:

- `migrations/007_stage3_1_7_mission_persistence_repository_model.sql`

No existing mission data is replaced by the migration.

## Health contract

`GET /health` now reports, among others:

- `control_version=stage3.1.7-mission-persistence-repository-model`
- `mission_repository_schema_version=apts-mission-repository-v1`
- `mission_persistence_manifest_schema_version=apts-mission-persistence-manifest-v1`
- `mission_repository_migration_level=7`
- `mission_repository_model=NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS`
- `mission_repository_source_of_truth=MISSION_ORCHESTRATOR_DATABASE`
- `mission_repository_recovery_mode=DURABLE_RECONSTRUCTION_NO_IN_MEMORY_SOURCE_OF_TRUTH`
- `mission_repository_integrity_mode=CANONICAL_HASH_AND_RELATIONAL_HEAD_CHAIN_VERIFICATION`
- `mission_repository_read_model_enabled=true`

The existing safety boundary remains unchanged:

- `dispatch_enabled=false`
- `target_action_dispatch_enabled=false`
- `target_actuation=false`

Stage 3.1.7 adds persistence/recovery evidence only; it grants no target execution authority.

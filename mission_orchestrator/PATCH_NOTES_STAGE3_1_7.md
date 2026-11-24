# Patch Notes — Stage 3.1.7 Mission Persistence & Repository Model

## Summary

This patch advances `mission_orchestrator` from Stage 3.1.6 Mission Versioning & Concurrency Mode to Stage 3.1.7 Mission Persistence & Repository Model.

Stage 3.1.7 turns the existing Stage-3 durable tables into an explicit repository contract with deterministic reconstruction, restart recovery evidence, and fail-closed integrity verification.

## Added

### `mission_orchestrator/repository_model.py`

Defines:

- repository schema/version constants;
- repository migration level and storage model;
- local source-of-truth/recovery/integrity modes;
- canonical persistence-manifest builder;
- stable SHA-256 domain for repository reconstruction;
- persistence-manifest self-verification.

### Repository metadata

New table:

- `mission_repository_metadata`

The singleton row records repository schema version, migration level, and storage model.

### Durable repository read model

New service/API:

- `GET /api/missions/{mission_id}/repository`

The endpoint reconstructs a mission entirely from durable Mission Orchestrator storage, verifies cross-table invariants, and returns a deterministic `repository_sha256`.

### Fail-closed integrity error

New exception/API mapping:

- `MissionRepositoryIntegrityError`
- HTTP `503 MISSION_REPOSITORY_INTEGRITY_ERROR`

### Persisted version-vector verification

Stage 3.1.6 version vectors stored in the command journal can now be re-verified without a live external observation.

### Regression coverage

Stage-3.1.7 tests prove:

- repository metadata and health contract;
- stable persistence-manifest hashing;
- hash revision after durable local mutation;
- projection across Stage-3.1.1 through 3.1.6 stores;
- independent service/repository restart reconstruction from the same durable database;
- repository reconstruction does not query live CTI;
- fail-closed detection of corrupted state projection;
- fail-closed detection of corrupted Scope head/hash;
- fail-closed detection of corrupted mission envelope;
- migration-007 authority boundary.

Current regression result: **82 passed**.

## Preserved

- Stage-3.1.1 immutable identity/envelope semantics.
- Stage-3.1.2 canonical state CAS and append-only transition ledger.
- Stage-3.1.3 immutable/versioned Scope/RoE/Constraint contract.
- Stage-3.1.4 external aptsGSS authority and immutable decision provenance.
- Stage-3.1.5 routing ownership/dispatch boundaries.
- Stage-3.1.6 version-vector concurrency and command journal.
- aptsGSS as policy/approval/revocation/emergency authority.
- VulnDesk/CTI as owner of CTI-local state/plan versions.
- target-action dispatch and target actuation remain disabled in Mission Orchestrator.

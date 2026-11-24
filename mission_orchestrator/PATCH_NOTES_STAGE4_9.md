# Patch Notes — Stage 4.9

## Added

- `pentest_subsystem/lineage_contract.py`
  - canonical Stage-4.9 control contract
  - seven canonical roadmap object types
  - type-constrained parent model
  - evidence/finding semantic validation
  - canonical lineage object hashing
  - durable lineage projection + integrity verifier
- `pentest_subsystem/lineage_repository.py`
  - migration level 7
  - append-only lineage persistence
  - exact replay/idempotency enforcement
  - parent/task/hash continuity verification
  - restart-safe ordered lineage reads
- `pentest_subsystem/lineage_service.py`
  - runtime activation/health projection
  - record materialization and semantic reference resolution
  - evidence/finding query services
  - durable task lineage reconstruction
- `pentest_migrations/007_stage4_9_evidence_finding_lineage_foundation.sql`
- `tests/test_stage4_9_evidence_finding_lineage_foundation.py`
- `STAGE4_9_ACCEPTANCE.ps1`

## Changed

- `pentest_subsystem/api_service.py`
  - added `PentestSubsystemStage49Handler`
  - current active server advanced to Stage 4.9
  - historical Stage-4.1…4.8 handlers retained
  - added Stage-4.9 contract/record/evidence/finding/lineage routes
- `pentest_subsystem/governance_repository.py`
  - predecessor initialization is now forward-compatible with Stage-4.9 subclass migration level 7 and no longer temporarily downgrades newer metadata
- `pentest_subsystem/__init__.py`
  - exports Stage-4.9 lineage contract/repository primitives
- `run/pentest_subsystem.py`
  - runtime description advanced to Stage 4.9

## Invariants

1. Every lineage object has identity, provenance, timestamp, parent reference, and integrity metadata.
2. Pentest task is the local root lineage anchor and remains bound to mission/PIP hashes.
3. Parent objects must pre-exist, be hash-exact, and belong to the same mission/pentest/task.
4. Evidence, observation, hypothesis, finding, action proposal, action result, and artifact semantics remain distinct.
5. Findings require canonical supporting evidence.
6. Artifacts reference content by URI/hash; inline raw bytes are rejected.
7. The lineage store is append-only and exact replay is idempotent.
8. Stage 4.9 does not mint authorization or execute target actions.

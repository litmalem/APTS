# Patch Notes — Stage 3.4.8 Retry, Fallback, Reassignment & Conflict Control

## Added

- Canonical immutable Stage-3.4.8 `DelegationRecoveryControl` contract with domain-separated SHA-256 integrity verification.
- Four explicit control-plane actions: `RETRY_CURRENT_OWNER`, `FALLBACK_NEXT_ELIGIBLE`, `REASSIGN_NEXT_ELIGIBLE`, and `FREEZE_OWNERSHIP_CONFLICT`.
- Bounded retry policy with a maximum of three admitted retries per immutable Stage-3.4.7 ownership receipt.
- Deterministic fallback/reassignment candidate derivation from the immutable Stage-3.4.4 ranked eligible candidate set only.
- Fail-closed no-alternate result when Stage 3.4.4 contains no next eligible candidate.
- Explicit proposal semantics: fallback/reassignment does not transfer ownership and requires fresh routing/Governance/delegation controls.
- Optimistic conflict control using caller `expected_control_count` plus repository transactional sequence checks.
- Immutable predecessor ID/SHA-256 chain across Stage-3.4.8 controls.
- Fail-closed conflict freeze that blocks follow-on recovery activity for the ownership receipt.
- Idempotent exact replay and conflict rejection for idempotency-key reuse with a changed canonical request.
- Strict request-field rejection for caller-selected fallback/recipient, runtime endpoint/health, resource assignment, Governance decision, dispatch, execution authorization, command, and target-action fields.
- Durable `mission_delegation_recovery_controls` persistence store.
- Migration `025_stage3_4_8_retry_fallback_reassignment_conflict_control.sql`.
- Repository read/list/idempotency methods, transactional CAS/sequence protection, manifest accounting, restart reconstruction, and integrity verification.
- Canonical event `MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED`.
- POST/GET API routes and Stage-3.4.8 definition endpoint.
- API error mapping for recovery-control conflict, guard rejection, and not-found conditions.
- 28 focused Stage-3.4.8 tests covering activation, definition, bounded retry, predecessor chaining, budget exhaustion, fallback/reassignment, no-alternate fail-closed behavior, deterministic candidate derivation, conflict freeze, CAS conflict protection, idempotency, forbidden fields, requester boundary, source immutability, event lineage, restart persistence, repository accounting, and tamper detection.

## Changed

- Runtime control version to `stage3.4.8-retry-fallback-reassignment-conflict-control`.
- Mission Orchestrator server version to `APTSMissionOrchestrator/3.4.8`.
- Repository migration level to `25`.
- Supported-control inventory now includes Stage 3.4.8.
- Repository persistence manifest and integrity model now include `mission_delegation_recovery_controls`.
- Historical tests that assert current runtime control, migration inventory, supported-control ordering, or current-runtime aggregate state were minimally rebased; their stage-local semantic assertions remain unchanged.

## Preserved authority boundaries

Stage 3.4.8 does not:

- mutate Stage-3.4.6 delegation/handoff evidence;
- mutate Stage-3.4.7 delivery/ACK/ownership evidence;
- transfer ownership to a fallback/reassignment candidate;
- re-resolve or expand the Stage-3.4.4 candidate set;
- resolve a runtime endpoint;
- probe runtime health;
- allocate an execution resource;
- perform external network I/O;
- dispatch work;
- authorize execution;
- issue a target command;
- actuate a target;
- issue a new Governance query;
- reuse Stage-3.4.5 authorization as an execution grant;
- extend the Mission version vector.

Authoritative pre-dispatch Governance revalidation remains mandatory for a later dispatch/execution stage.

## Validation

- Python compile: PASS.
- Exhaustive partitioned regression: `745 passed`.
- Focused Stage 3.4.8: `28 passed`.

Cumulative regression checkpoints:

```text
Stage 3.1 closure                 111
Stage 3.2 cumulative             267
Stage 3.3 cumulative             506
Stage 3.4.1 cumulative           525
Stage 3.4.2 cumulative           551
Stage 3.4.3 cumulative           586
Stage 3.4.4 cumulative           636
Stage 3.4.5 cumulative           666
Stage 3.4.6 cumulative           698
Stage 3.4.7 cumulative           717
Stage 3.4.8 cumulative           745
```

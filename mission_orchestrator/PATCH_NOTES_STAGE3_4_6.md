# Patch Notes — Stage 3.4.6 Canonical Delegation Contract & Handoff Envelope

## Added

- Canonical `DelegationContract` with domain-separated SHA-256 integrity verification.
- Canonical nested `HandoffEnvelope` carrying logical recipient, complete task/work context, authority context, canonical source-artifact references, and provenance.
- Strict Stage-3.4.5 `AUTHORIZED` prerequisite with freshness checks against current Mission state/version, active Plan, planned task, Mission scope, Stage-3.4.4 route, and Governance binding.
- Canonical Stage-3.4.6 request normalization and request fingerprinting.
- Fail-closed rejection of caller-supplied recipient, endpoint, handoff, dispatch, ownership, execution, or target-action fields.
- Durable `mission_task_delegations` repository store.
- Migration `023_stage3_4_6_canonical_delegation_contract_handoff_envelope.sql`.
- SQLite and MySQL transactional persistence guards for active Plan, task, scope, Governance binding, and authorization freshness.
- Repository read/list/idempotency/authorization correlation methods for Stage 3.4.6.
- Repository manifest, direct-record counts, restart reconstruction, and integrity verification for the Stage-3.4.6 store and lineage.
- Canonical event `MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED`.
- Stage-3.4.6 POST/GET API routes and definition endpoint.
- API error mapping for delegation conflict, guard rejection, and not-found conditions.
- 32 focused Stage-3.4.6 tests covering happy path, canonical envelope content, source binding, idempotency, duplicate protection, denied authorization, stale evidence, forbidden fields, event lineage, restart reconstruction, and tamper detection.

## Changed

- Runtime control version to `stage3.4.6-canonical-delegation-contract-handoff-envelope`.
- Mission Orchestrator server version to `APTSMissionOrchestrator/3.4.6`.
- Repository migration level to `23`.
- Supported-control inventory now includes Stage 3.4.6.
- Historical runtime-inventory assertions were rebased to current control/migration/store/event inventory.
- Stage-3.4.2 through Stage-3.4.5 health tests now correctly observe the aggregate current-runtime fact `task_routing_delegation_performed=true`; their stage-local authority boundaries remain unchanged.

## Preserved authority boundaries

Stage 3.4.6 performs a **logical control-plane delegation** and materializes the handoff envelope, but it does not:

- transmit the handoff envelope;
- acknowledge delivery;
- accept ownership on behalf of the recipient;
- resolve a runtime endpoint;
- probe runtime health;
- allocate a concrete execution resource;
- dispatch work;
- authorize target execution;
- actuate any target;
- issue a new Governance query;
- reuse Stage-3.4.5 authorization as a target-execution grant;
- extend the Mission version vector.

Authoritative pre-dispatch Governance revalidation remains mandatory for any later dispatch/execution control.

## Validation

- Python compile: PASS.
- Complete collection: `698 tests`.
- Exhaustive partitioned regression: `698 passed`.
- Focused Stage 3.4.6: `32 passed`.

Cumulative regression checkpoints remain coherent:

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
```

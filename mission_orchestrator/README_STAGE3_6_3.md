# Stage 3.6.3 — Evidence Binding Verification

## Purpose

Stage 3.6.3 consumes the successful, completion-eligible task lineage established by Stages 3.5.7, 3.6.1, and 3.6.2 and creates one immutable `ebind-*` verification record. Its job is deliberately narrow: verify that the evidence/artifact manifest references and SHA-256 bindings carried forward through the execution-result, task-outcome, and terminality artifacts remain internally consistent and refer to the same active Plan/task lineage.

```text
Stage 3.5.7  xresult-*   evidence/artifact reference manifests
       |          \
       |           +-- manifest IDs/counts/SHA-256 + source result hash
       v
Stage 3.6.1  toutcome-*  canonical task-outcome identity
       |
       v
Stage 3.6.2  telig-*     TERMINAL_SUCCESS + completion eligible
       |
       v
Stage 3.6.3  ebind-*     immutable evidence-binding verification
       |
       +--> Stage 3.6.4
```

Stage 3.6.3 is **not** content attestation. It does not dereference evidence/artifact URIs or recompute hashes from external bytes. It verifies the locally persisted immutable reference manifests and their cross-stage hash bindings.

## Runtime identity

```text
control_version             = stage3.6.3-evidence-binding-verification
server_version              = APTSMissionOrchestrator/3.6.3
repository_migration_level  = 38
persistence_store           = mission_task_evidence_binding_verifications
identity_prefix             = ebind-
verification_status         = VERIFIED
next_stage                  = 3.6.4
```

## Canonical contract

Implementation:

```text
mission_orchestrator/task_evidence_binding.py
```

Canonical constants:

```text
stage_schema_version = apts-task-evidence-binding-verification-v1
schema_version       = apts-task-evidence-binding-verification-contract-v1
identity_prefix      = ebind-
mode                 = DETERMINISTIC_LOCAL_REFERENCE_AND_HASH_BINDING_VERIFICATION_NO_CONTENT_DEREFERENCE_NO_ACCEPTANCE_COMMIT
authority            = MISSION_ORCHESTRATOR_TASK_EVIDENCE_BINDING_VERIFICATION
status               = VERIFIED
```

The `ebind-*` contract binds the current Mission state/version, current active `pver-*`, exact `toutcome-*`, exact `telig-*`, and exact `xresult-*`. It verifies:

- cross-stage Mission / Plan / planned-task / task-key identity consistency;
- `toutcome-* -> xresult-*` canonical hash binding;
- `telig-* -> toutcome-*` canonical hash binding;
- Stage-3.5.7 evidence/artifact item schema and unique item identifiers;
- evidence/artifact reference counts;
- canonical manifest SHA-256 recomputation from the persisted manifest-item structures;
- propagation of evidence/artifact manifest hashes into Stage 3.6.1;
- reference-only persistence (`inline_payload_persisted=false`).

## Preconditions

Stage 3.6.3 fails closed unless:

```text
Stage 3.6.1 source status = VERIFIED_COMPLETED
Stage 3.6.2 terminality   = TERMINAL_SUCCESS
Stage 3.6.2 eligibility   = ELIGIBLE_FOR_COMPLETION_EVALUATION
completion_eligible       = true
all source artifacts      = current, immutable, integrity-valid, same Plan/task lineage
```

## Authority boundary

The following remain explicitly false:

```text
evidence_content_dereferenced
artifact_content_dereferenced
external_content_hash_recomputed
content_authenticity_attestation_performed

task_outcome_acceptance_performed
acceptance_criteria_evaluation_performed
task_completion_commit_performed
task_state_transition_performed
dependency_release_performed
readiness_recalculation_performed
plan_progression_performed
mission_success_completion_authority_exercised

governance_query_performed
runtime_query_performed
runtime_control_io_performed
dispatch_redelivery_performed
new_execution_attempt_created
new_target_action_dispatch_performed
external_network_io_performed
target_actuation
mission_state_transition_performed
```

Therefore:

```text
EVIDENCE BINDING VERIFIED != CONTENT AUTHENTICITY ATTESTED
EVIDENCE BINDING VERIFIED != TASK OUTCOME ACCEPTED
EVIDENCE BINDING VERIFIED != TASK COMPLETION COMMITTED
```

## Persistence

Migration:

```text
migrations/038_stage3_6_3_evidence_binding_verification.sql
```

New durable store:

```text
mission_task_evidence_binding_verifications
```

Uniqueness guards enforce one immutable verification per eligibility gate, task outcome, and Plan/task identity, plus canonical request idempotency.

Repository reconstruction now includes `task_evidence_binding_verification_store` and cross-checks every verification against the persisted Stage-3.5.7, 3.6.1, and 3.6.2 source artifacts and its exactly-once lineage event.

## API surface

```text
POST /api/missions/{mission_id}/task-evidence-binding-verifications
GET  /api/missions/{mission_id}/task-evidence-binding-verifications
GET  /api/missions/{mission_id}/task-evidence-binding-verifications/{verification_id}
GET  /api/missions/{mission_id}/task-evidence-binding-verification-definition
```

## Event lineage

New event:

```text
MISSION_TASK_EVIDENCE_BINDING_VERIFIED
```

Its `causation_id` is the immutable `ebind-*` verification identity.

## Test coverage

`tests/test_stage3_6_3_evidence_binding_verification.py` adds 20 focused tests for runtime identity, contract definition, success path, exact source binding, reference-only authority boundaries, stale source rejection, missing-source fail-closed behavior, forbidden caller overrides, idempotency, uniqueness, zero Governance/runtime I/O, durable restart, exactly-once event lineage, repository integrity and tamper detection, API/migration registration, deterministic derivation, and malformed/noneligible source rejection.

Canonical inventory after this stage: **1022 tests**.

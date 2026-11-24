# Stage 3.7.6 — Replan Candidate Validation & Delta Feasibility Gate

Stage 3.7.6 adds a deterministic, fail-closed validation gate between the immutable Stage-3.7.5 ReplanCandidate and any later replan commit/supersession authority.

## Runtime identity

```text
control_version = stage3.7.6-replan-candidate-validation-delta-feasibility-gate
repository migration = 50
validation identity prefix = rpdec-
validation event = MISSION_REPLAN_DECISION_RECORDED
persistence store = mission_replan_decisions
```

The gate emits one of two canonical statuses:

```text
VALIDATED_FOR_COMMIT
REJECTED_INFEASIBLE
```

`VALIDATED_FOR_COMMIT` is an eligibility result only. It does not create or activate a successor Plan and does not itself commit replanning.

## Validation model

The gate verifies the Stage-3.7.5 candidate and Stage-3.7.4 snapshot, then deterministically reproduces the Stage-3.7.5 candidate payload and evaluates delta feasibility. Checks include source binding, current Plan-head and Mission-version drift guards, next Plan-version/generation rules, canonical task ordering, source-task identity/hash binding, completed-task non-recurrence, dependency endpoint validity, self-dependency rejection, DAG acyclicity, satisfied-predecessor completion evidence, and count consistency. Empty deltas fail closed.

## Persistence and lineage

Migration 050 creates `mission_replan_decisions`. A newly materialized decision records exactly one canonical Mission event, `MISSION_REPLAN_DECISION_RECORDED`, and is bound to the candidate, snapshot, adaptation episode, source Plan/version, source Mission version, idempotency request hash, validation findings, and canonical decision SHA-256.

Cardinality is fail-closed: one decision per candidate, one decision per adaptation episode, and unique `(mission_id, idempotency_key)` semantics. Exact retries recover the existing durable decision; conflicting reuse is rejected.

## API surface

```text
POST /api/missions/{mission_id}/replan-candidates/{replan_candidate_id}/validation
GET  /api/missions/{mission_id}/replan-candidates/{replan_candidate_id}/validation
GET  /api/missions/{mission_id}/replan-validations
GET  /api/missions/{mission_id}/replan-validations/{replan_validation_id}
GET  /api/missions/{mission_id}/replan-candidate-validation-delta-feasibility-definition
```

No Stage-3.7.6 endpoint grants replan commit, Plan supersession, routing, dispatch, execution, or target actuation.

## Authority boundary

Stage 3.7.6 performs candidate/snapshot integrity verification, deterministic candidate reproduction, Plan-delta validation, feasibility evaluation, decision persistence, decision-event lineage, idempotent recovery, and repository reconstruction checks.

It does **not** perform successor Plan creation/activation, replan commit, Plan supersession, historical Plan mutation, Mission-state transition, Governance refresh/query, external-context refresh, routing/delegation, execution dispatch, execution-attempt creation, or target actuation.

The next planned control is **Stage 3.7.7**.

## Validation evidence in this build workspace

```text
python -m compileall -q mission_orchestrator tests              -> PASS
python -m pytest --collect-only -q                              -> 1282 tests collected
focused Stage 3.7.6                                             -> 25 passed in 28.02s
Stage-3.7.5 + historical current-head probes                    -> 23 passed in 23.53s
```

Several historical regression partitions were also executed successfully during development. A single uninterrupted full 1282-test run was not completed within the available execution window, so formal target-host acceptance remains pending until `STAGE3_7_6_ACCEPTANCE.ps1` completes with PASS.

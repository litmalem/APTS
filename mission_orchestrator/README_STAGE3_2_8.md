# Stage 3.2.8 — Cleanup & Verified Completion Gate

Stage 3.2.8 converts `BEGIN_CLEANUP -> CLEANING_UP -> COMPLETE -> COMPLETED` from a topology-only path into a durable, fail-closed completion protocol. A mission may enter cleanup only from a lineage that can be traced back to the Stage-3.2.4 `START -> RUNNING` activation, and it may reach `COMPLETED` only after the caller supplies a structured completion declaration whose objective, success criteria, cleanup checks, dependencies, and evidence bindings are verified locally.

This stage verifies Mission lifecycle completion only. It does **not** perform target cleanup, execute a target action, decide Governance authorization, query aptsGSS, invoke the planner, or fabricate success evidence.

## Contract

Schema: `apts-mission-cleanup-completion-gate-v1`

Mode: `DURABLE_CLEANUP_LINEAGE_AND_EVIDENCE_GATED_VERIFIED_COMPLETION_FAIL_CLOSED`

Authority semantics:

`MISSION_LIFECYCLE_COMPLETION_VERIFICATION_ONLY_NOT_GOVERNANCE_AUTHORIZATION_OR_TARGET_EXECUTION`

Lifecycle path:

`RUNNING | PAUSED -> BEGIN_CLEANUP -> CLEANING_UP -> COMPLETE -> COMPLETED`

`ABORT`, `FAIL`, and `EXPIRE` remain available from `CLEANING_UP` under the Stage-3.2.7 typed terminal semantics.

## BEGIN_CLEANUP

`BEGIN_CLEANUP` does not claim that cleanup has already happened. It creates durable `mission_cleanup_control` evidence in the existing append-only transition metadata. The evidence records:

- deterministic `cleanup_id`;
- exact source state and source state version;
- valid Stage-3.2.4 RUNNING activation proof;
- actor, reason, and evidence references;
- optional `metadata.cleanup` context;
- active pause context when cleanup starts from `PAUSED`;
- completion blockers inherited from unresolved waiting/replanning context;
- `cleanup_started=true` and `cleanup_verified=false`;
- `verified_completion_claimed=false`;
- explicit no-Governance/no-target-execution semantics.

A direct/legacy transition into `CLEANING_UP` does not fabricate Stage-3.2.8 cleanup evidence.

## Completion blockers

A PAUSED mission may enter `CLEANING_UP`, but the cleanup record can remain blocked from verified completion. Stage 3.2.8 currently records blockers such as:

- `UNRESOLVED_WAITING_DEPENDENCY`;
- `UNRESOLVED_REPLAN`;
- `PAUSED_SOURCE_NOT_RUNNING`.

The `COMPLETE` guard rejects a mission while any cleanup-completion blocker remains.

## COMPLETE verification request

The command-level `evidence_refs` must be non-empty. The command metadata must contain a `completion` object with this logical contract:

```json
{
  "completion": {
    "verification_status": "VERIFIED",
    "objective_status": "SATISFIED",
    "objective_evidence_refs": ["evidence:objective:..."],
    "success_criteria_status": "SATISFIED",
    "criteria_results": [
      {
        "criterion_index": 0,
        "status": "SATISFIED",
        "evidence_refs": ["evidence:criterion:0:..."]
      }
    ],
    "cleanup_status": "VERIFIED",
    "cleanup_checks": [
      {
        "check_id": "CONTROLLED_CLEANUP_VERIFIED",
        "status": "PASS",
        "evidence_refs": ["evidence:cleanup:..."]
      }
    ],
    "outstanding_critical_dependencies": 0
  }
}
```

The guard requires all of the following:

1. current state is `CLEANING_UP` under the canonical topology;
2. valid Stage-3.2.4 RUNNING activation lineage exists;
3. canonical mission-envelope integrity remains valid;
4. valid Stage-3.2.8 `BEGIN_CLEANUP` lineage exists;
5. cleanup-completion blockers are empty;
6. `verification_status=VERIFIED`;
7. `objective_status=SATISFIED` with objective evidence;
8. every canonical mission success criterion is represented **exactly once** by `criterion_index`, all with `status=SATISFIED` and evidence;
9. `cleanup_status=VERIFIED` with at least one cleanup check, every check has `status=PASS` and evidence;
10. `outstanding_critical_dependencies=0`;
11. every nested objective/criterion/cleanup evidence reference is bound to the command-level `evidence_refs`.

Failure of any check rejects the transition before state/event persistence.

## Durable verified completion evidence

A successful `COMPLETE` persists `mission_completion_verification` in the transition metadata. It contains:

- deterministic `completion_id`;
- associated `cleanup_id` and cleanup transition;
- Stage-3.2.4 run-activation proof;
- canonical envelope hash used by the verification;
- the verified completion declaration;
- complete criteria results and cleanup checks;
- command evidence references;
- `verified_completion_claimed=true`;
- `cleanup_completion_gate_applied=true`;
- immutable finality semantics;
- explicit no-Governance/no-target-execution semantics.

The terminal read model reconstructs a valid Stage-3.2.8 completion as:

`VALID_VERIFIED_COMPLETION`

A direct/legacy transition to `COMPLETED` is preserved for Stage-3.1 compatibility but is explicitly reported as:

`LEGACY_DIRECT_COMPLETED_NO_STAGE_3_2_8_EVIDENCE`

It does not receive a false verified-completion claim.

## Read API

Stage 3.2.8 adds:

`GET /api/missions/{mission_id}/cleanup-completion-contract`

The projection reports run lineage, cleanup lineage, blockers, completion readiness, and the exact request contract. Lifecycle discovery also embeds this projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

Discovery can show `COMPLETE` as guard-eligible when structural prerequisites are ready while marking that request-specific completion evidence is required at execution time.

## Guard-matrix extension

Stage 3.2.8 activates these local guards:

- `RUN_ACTIVATION_LINEAGE_FOR_CLEANUP`;
- `CANONICAL_ENVELOPE_INTEGRITY_FOR_CLEANUP_COMPLETION`;
- `CLEANUP_LINEAGE_FOR_COMPLETION`;
- `CLEANUP_COMPLETION_BLOCKERS_CLEAR`;
- `COMPLETION_DECLARATION_VERIFIED`;
- `COMPLETION_OBJECTIVE_SATISFIED`;
- `COMPLETION_SUCCESS_CRITERIA_COVERAGE`;
- `COMPLETION_CLEANUP_VERIFIED`;
- `COMPLETION_CRITICAL_DEPENDENCIES_CLEAR`;
- `COMPLETION_EVIDENCE_REFS_BOUND`.

All checks are local and deterministic. Governance authorization remains external to aptsGSS.

## Persistence and idempotency

Stage 3.2.8 reuses the existing:

- Stage-3.1.6 command journal/idempotency gate;
- Stage-3.1.2 append-only transition ledger;
- Stage-3.1.9 Mission event lineage;
- transition metadata for cleanup/completion evidence.

No new table or migration is introduced. Repository migration level remains **8**.

An exact retry of a successfully persisted `COMPLETE` command is replay-safe and does not create duplicate state transitions or Mission events.

## Authority boundary

Stage 3.2.8 explicitly preserves:

- `governance_authorization_authority = EXTERNAL_APTS_GSS`;
- `mission_completion_governance_query_performed = false`;
- `mission_completion_authorization_granted = false`;
- `mission_completion_execution_authorized = false`;
- `mission_cleanup_action_performed_by_orchestrator = false`;
- `target_action_dispatch_enabled = false`;
- `target_actuation = false`.

`cleanup_status=VERIFIED` is therefore a caller-supplied evidence assertion validated by the Mission lifecycle gate; it is **not** a claim that Mission Orchestrator executed cleanup against a target.

## Deliberately deferred

Stage 3.2.8 does not implement:

- automatic target cleanup or compensation execution;
- planner invocation or autonomous plan artifact generation;
- external evidence retrieval/validation against aptsGSS or CTI;
- automatic completion based only on elapsed state;
- automatic retry/recovery from terminal state;
- target-action dispatch or actuation;
- Stage 3.2.9 event-driven lifecycle automation.

## Regression baseline

`234 passed`.

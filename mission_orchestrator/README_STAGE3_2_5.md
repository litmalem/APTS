# Stage 3.2.5 — Waiting States: Evidence & Approval Dependency Control

Stage 3.2.5 turns `WAITING_EVIDENCE` and `WAITING_APPROVAL` from topology-only lifecycle states into explicit, durable dependency-control states. A mission may enter either waiting state only through a typed dependency declaration, and it may return to `RUNNING` through `START` only when the active dependency is resolved with a matching `SATISFIED` declaration plus non-empty evidence references.

This stage controls Mission lifecycle dependencies only. It does **not** decide Governance authorization, does not query aptsGSS, and does not authorize or dispatch target execution.

## Contract

Schema: `apts-mission-waiting-dependency-control-v1`

Mode: `EXPLICIT_WAIT_DECLARATION_AND_LOCAL_RESOLUTION_EVIDENCE_FAIL_CLOSED`

Supported wait commands:

- `WAIT_FOR_EVIDENCE` → `WAITING_EVIDENCE` with dependency kind `EVIDENCE`;
- `WAIT_FOR_APPROVAL` → `WAITING_APPROVAL` with dependency kind `APPROVAL`.

Return command:

- `START` from either waiting state → `RUNNING`.

Required resolution status: `SATISFIED`.

## Wait declaration request

The Stage-3.2.1 lifecycle command envelope is unchanged. Stage 3.2.5 uses the existing `metadata` extension field.

Example:

```json
{
  "command": "WAIT_FOR_EVIDENCE",
  "evidence_refs": ["evidence:request:123"],
  "metadata": {
    "dependency": {
      "dependency_id": "dep-evidence-123",
      "kind": "EVIDENCE",
      "description": "Await verification artifact"
    }
  }
}
```

The dependency declaration is stored inside the existing append-only transition metadata as `mission_waiting_dependency`.

A missing declaration, malformed dependency id, or kind mismatch fails closed before state mutation.

## Resolution request

Returning from `WAITING_EVIDENCE` or `WAITING_APPROVAL` through `START` requires:

1. valid Stage-3.2.5 waiting dependency lineage for the current waiting state;
2. `metadata.dependency_resolution.dependency_id` matching the active dependency;
3. `metadata.dependency_resolution.status = SATISFIED`;
4. a non-empty `resolved_by` value;
5. non-empty lifecycle-command `evidence_refs`.

Example:

```json
{
  "command": "START",
  "evidence_refs": ["evidence:artifact:123"],
  "metadata": {
    "dependency_resolution": {
      "dependency_id": "dep-evidence-123",
      "status": "SATISFIED",
      "resolved_by": "operator-01"
    }
  }
}
```

Successful return evidence is stored in transition metadata as `mission_waiting_dependency_resolution`.

## Approval is not Governance authorization

`WAIT_FOR_APPROVAL` models an external/human/workflow dependency in the Mission lifecycle. A satisfied approval dependency is **not** an aptsGSS `PolicyDecision`, does not grant `ALLOW`, and does not authorize target execution.

Stage 3.2.5 explicitly reports:

- `approval_dependency_is_governance_authorization = false`;
- `governance_authorization_query_performed = false`;
- `authorization_granted = false`;
- `execution_authorized = false`;
- `target_action_dispatch_enabled = false`;
- `target_actuation = false`.

Governance authority remains `EXTERNAL_APTS_GSS`.

## Read API

`GET /api/missions/{mission_id}/waiting-dependency-contract`

The projection exposes:

- current waiting state;
- active dependency lineage and transition id;
- dependency id and kind;
- wait-command metadata requirements;
- return-command resolution requirements;
- explicit non-authorization semantics.

The existing lifecycle discovery endpoint also embeds the `waiting_dependency` projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

Discovery can identify topology and existing waiting lineage, while request-specific declaration/resolution fields are validated at execution time.

## Guard-matrix extension

Stage 3.2.5 adds:

- `WAITING_DEPENDENCY_DECLARATION_FOR_WAIT`;
- `WAITING_DEPENDENCY_LINEAGE_FOR_RETURN`;
- `WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN`;
- `WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN`.

A legacy direct transition into `WAITING_EVIDENCE` or `WAITING_APPROVAL` does not fabricate Stage-3.2.5 dependency evidence and therefore cannot use `START` to bypass the dependency gate.

`REPLAN`, `PAUSE`, `ABORT`, `FAIL`, and `EXPIRE` retain their existing lifecycle semantics. In particular, Stage 3.2.5 does not require dependency satisfaction before `REPLAN`, allowing the orchestrator to abandon an unsatisfied dependency and move into replanning.

## Persistence and lineage

No new database table or migration is introduced. Stage 3.2.5 reuses:

- Stage-3.1.6 command journal and idempotency gate;
- Stage-3.1.2 append-only state transition ledger;
- Stage-3.1.9 Mission event lineage;
- transition metadata for declaration/resolution evidence.

Repository migration level remains **8**.

## Deliberately deferred

Stage 3.2.5 does not implement:

- Stage 3.2.6 pause/resume/replanning policy extension;
- external event subscription or automatic dependency completion;
- autonomous planner execution;
- verified cleanup/completion gate (Stage 3.2.8);
- target-action dispatch or actuation.

## Regression baseline

`182 passed`.

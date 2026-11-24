# Stage 3.7.7 — Authoritative Replan Commit Authorization & Successor Plan Materialization

Stage 3.7.7 turns a Stage-3.7.6 `VALIDATED_FOR_COMMIT` result into an authoritative, durable replan commit only after a fresh fail-closed Governance authorization check. On success, the Mission Orchestrator atomically appends a successor Plan version and advances the active Plan head with compare-and-swap semantics.

## Runtime identity

```text
control_version = stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization
repository migration = 51
commit identity prefix = rpcom-
commit event = MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED
commit status = COMMITTED_SUCCESSOR_PLAN
persistence store = mission_replan_commits
```

The commit-time Governance action is:

```text
action_class = INTERNAL_REASONING
action_name  = AUTHORIZE_REPLAN_COMMIT
resource     = MISSION
```

## Commit protocol

The service accepts only an immutable Stage-3.7.6 decision with status `VALIDATED_FOR_COMMIT`. It re-verifies the exact Stage-3.7.5 candidate, Stage-3.7.4 snapshot, Stage-3.7.3 eligibility lineage, source Mission version, source Plan version, active Plan head, Mission scope snapshot, and Governance binding. Any drift fails closed before successor materialization.

Immediately before commit, the service performs an authoritative Governance revalidation. The commit can continue only when the decision is `ALLOW` and `requires_human_approval == false`. The request is assigned a deterministic `rpcaop-*` operation identity so response-loss recovery can reuse the authoritative decision instead of issuing a duplicate authorization request.

## Successor Plan materialization

After authorization, Stage 3.7.7 deterministically materializes the validated Stage-3.7.5 candidate into the canonical Plan-version contract. The successor version is exactly `predecessor + 1`. The predecessor Plan row remains immutable; supersession is represented by advancing the active Plan head, not by rewriting historical Plan artifacts.

The following persistence operations are committed in one database transaction:

1. append the successor Plan-version artifact;
2. compare-and-swap the active Plan head from the expected predecessor to the successor;
3. persist the canonical `rpcom-*` replan commit record.

A stale active head, stale source Mission state/version, duplicate validation commit, or conflicting idempotency key aborts the transaction.

## Event lineage

A successful commit guarantees the canonical commit event:

```text
MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED
```

and preserves the existing Plan-version supersession lineage event:

```text
MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED
```

Repository reconstruction verifies the commit contract, source validation/candidate/snapshot lineage, predecessor/successor Plan artifacts, active-head relationship, and expected events.

## API surface

```text
POST /api/missions/{mission_id}/replan-validations/{replan_validation_id}/commit
GET  /api/missions/{mission_id}/replan-validations/{replan_validation_id}/commit
GET  /api/missions/{mission_id}/replan-commits
GET  /api/missions/{mission_id}/replan-commits/{replan_commit_id}
GET  /api/missions/{mission_id}/authoritative-replan-commit-successor-plan-materialization-definition
```

The API rejects caller-supplied successor tasks, successor Plan payloads, Governance outcomes, Mission lifecycle transitions, routing/delegation, execution dispatch, or target actuation instructions.

## Authority boundary

Stage 3.7.7 **does** authorize the commit, persist the canonical replan decision, create the successor Plan version, and advance the active Plan head.

Stage 3.7.7 does **not** mutate historical Plan rows, transition Mission lifecycle state, route/delegate tasks, create execution attempts, dispatch target actions, or actuate external targets. The Mission remains in its current adaptive source state while the Plan lineage advances.

The next planned control is **Stage 3.7.8**.

## Validation evidence in this build workspace

```text
python -m compileall -q mission_orchestrator tests              -> PASS
python -m pytest --collect-only -q                              -> 1304 tests collected
focused Stage 3.7.7                                             -> 22 passed in 27.37s
manual Stage-3.7.7 commit/repository-reconstruction smoke       -> PASS
```

An uninterrupted full 1304-test regression did not complete within the available workspace runtime window. Formal target-host acceptance therefore remains pending until `STAGE3_7_7_ACCEPTANCE.ps1` completes with PASS.

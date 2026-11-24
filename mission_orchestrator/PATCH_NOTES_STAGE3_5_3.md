# Patch Notes — Stage 3.5.3

Stage 3.5.3 adds authoritative pre-dispatch Governance revalidation between durable Stage-3.5.2 eligibility and all later runtime-dispatch controls.

The patch introduces the canonical append-only `xreval-*` evidence contract. Before any authoritative decision is requested, the Mission Orchestrator re-reads the current Mission/Plan/dispatch/eligibility/readiness/delegation/scope/binding/registry artifacts and re-evaluates the Stage-3.5.2 static preconditions fail-closed. The authoritative Governance scope is then rechecked against the immutable Mission binding and a fresh `TASK_EXECUTION / AUTHORIZE_EXECUTION_DISPATCH` PolicyDecision is issued or recovered through a deterministic operation id.

`ALLOW` grants execution authorization only. `DENY` and `REVIEW` remain fail-closed. None of the outcomes performs endpoint resolution, health probing, resource assignment, dispatch, external target I/O, or target actuation.

Engineering changes include migration level 29, the durable `mission_pre_dispatch_governance_revalidations` store, canonical hashing/verification, idempotency and response-loss recovery, REST routes, lineage event `MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED`, repository reconstruction/integrity coverage, Stage-3.5.3 health declarations, server/control version activation, compatibility assertion rebasing, and a 19-test focused suite.

# Stage 3.7.2 — Adaptation Trigger Detection & Classification

## Purpose

Stage 3.7.2 advances the Stage-3.7 adaptation/replanning pipeline from **immutable trigger detection** to **deterministic trigger classification**. It consumes an existing Stage-3.7.1 `DETECTED` AdaptationEpisode/ReplanTrigger, verifies the exact detection evidence and current Mission/Plan concurrency bindings, then materializes a separate immutable classification record.

The stage answers four bounded questions only:

1. What canonical adaptation reason best refines the Stage-3.7.1 trigger?
2. What severity was assigned to that reason?
3. From which canonical subsystem/stage was the condition observed?
4. Does the reason map to a Level-3 partial-plan scope or a Level-4 mission scope?

It does **not** decide whether replanning is authorized or eligible. It does not issue lifecycle `REPLAN`, call the planner, create or validate a successor Plan, supersede a Plan, dispatch work, or actuate any target.

## Runtime identity

```text
control_version = stage3.7.2-adaptation-trigger-detection-classification
server_version  = APTSMissionOrchestrator/3.7.2
repository_migration_level = 46
migration = migrations/046_stage3_7_2_adaptation_trigger_detection_classification.sql
persistence_store = mission_adaptation_trigger_classifications
```

Stage 3.7.1 remains a distinct predecessor contract:

```text
Stage-3.7.1 migration metadata = 45
Stage-3.7.1 store              = mission_adaptation_replan_contracts
Stage-3.7.1 stored episode     = DETECTED
```

Stage 3.7.2 never rewrites that source contract. A read projection may expose the episode's **effective** state as `CLASSIFIED` once the independent classification record exists.

## Classification contract

```text
stage schema    = apts-adaptation-trigger-detection-classification-v1
contract schema = apts-adaptation-trigger-classification-contract-v1
identity prefix = rcls-
status          = CLASSIFIED
event           = MISSION_ADAPTATION_TRIGGER_CLASSIFIED
mode            = EVIDENCE_BOUND_DETERMINISTIC_ADAPTATION_TRIGGER_CLASSIFICATION_NO_ELIGIBILITY_NO_REPLAN_NO_PLANNER_NO_ACTUATION
authority       = MISSION_ORCHESTRATOR_ADAPTATION_TRIGGER_CLASSIFICATION
```

Each classification is canonically hashed and linked to:

- Mission ID;
- Stage-3.7.1 AdaptationEpisode ID (`adpt-*`);
- Stage-3.7.1 ReplanTrigger ID (`rpln-*`);
- exact Stage-3.7.1 canonical contract hash;
- exact `MISSION_ADAPTATION_REPLAN_DETECTED` event ID/hash;
- exact current Mission state/version vector;
- exact active Stage-3.3 Plan-version head;
- source trigger/evidence material;
- canonical reason, severity, source stage, and replan-scope classification.

## Canonical reason taxonomy

```text
EXECUTION_FAILURE
EXECUTION_TIMEOUT_EXHAUSTED
TASK_OUTCOME_REJECTED
DEPENDENCY_INVALIDATED
RESOURCE_UNAVAILABLE
AGENT_CAPABILITY_CHANGED
ENVIRONMENT_STATE_CHANGED
MISSION_CONSTRAINT_CHANGED
BUDGET_PRESSURE
DEADLINE_RISK
POLICY_CHANGED
EVIDENCE_CONTRADICTION
PLAN_STALE
```

Severity taxonomy:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Source-stage taxonomy:

```text
STAGE3_3_PLANNING
STAGE3_4_ROUTING_DELEGATION
STAGE3_5_EXECUTION
STAGE3_6_OUTCOME_COMPLETION
MISSION_LIFECYCLE
GOVERNANCE
ENVIRONMENT
OPERATOR
OTHER
```

## Deterministic replan-scope classification

Stage 3.7.2 classifies reasons into two **scope indicators**, not authorization decisions.

### Level 3 — partial-plan scope

```text
EXECUTION_FAILURE
EXECUTION_TIMEOUT_EXHAUSTED
TASK_OUTCOME_REJECTED
DEPENDENCY_INVALIDATED
RESOURCE_UNAVAILABLE
AGENT_CAPABILITY_CHANGED
PLAN_STALE
```

Projection:

```text
replan_scope_level = LEVEL_3_PARTIAL_PLAN
replan_scope       = PARTIAL_PLAN
```

### Level 4 — mission scope

```text
ENVIRONMENT_STATE_CHANGED
MISSION_CONSTRAINT_CHANGED
BUDGET_PRESSURE
DEADLINE_RISK
POLICY_CHANGED
EVIDENCE_CONTRADICTION
```

Projection:

```text
replan_scope_level = LEVEL_4_MISSION
replan_scope       = MISSION_LEVEL
```

The classification layer deliberately does not expose an `AI_THINKS_REPLAN=true` style signal. Scope identifies the breadth of the observed adaptation condition; later controls decide eligibility and authority.

## Stage-3.7.1 trigger compatibility

Stage-3.7.1 trigger codes are coarse. Stage 3.7.2 permits only compatible refinements. Examples:

```text
TASK_FAILURE       -> EXECUTION_FAILURE | TASK_OUTCOME_REJECTED | PLAN_STALE
TASK_TIMEOUT       -> EXECUTION_TIMEOUT_EXHAUSTED | DEADLINE_RISK | PLAN_STALE
DEPENDENCY_CHANGE  -> DEPENDENCY_INVALIDATED | PLAN_STALE
RESOURCE_CHANGE    -> RESOURCE_UNAVAILABLE | AGENT_CAPABILITY_CHANGED | BUDGET_PRESSURE | PLAN_STALE
POLICY_CHANGE      -> POLICY_CHANGED | MISSION_CONSTRAINT_CHANGED | PLAN_STALE
CTI_CHANGE         -> ENVIRONMENT_STATE_CHANGED | POLICY_CHANGED | EVIDENCE_CONTRADICTION | PLAN_STALE
OTHER              -> any canonical Stage-3.7.2 reason, still evidence-bound
```

An incompatible refinement fails closed.

## Guard and concurrency model

Classification requires all of the following:

```text
existing Stage-3.7.1 DETECTED episode
exact Stage-3.7.1 contract SHA-256
exact Stage-3.7.1 detection-event SHA-256
current Mission version SHA-256
current Mission state_version
current active Plan version-record ID
current active Plan version
current active Plan SHA-256
evidence-backed Stage-3.7.1 trigger material
```

If Mission state changed after detection, or the active Plan head no longer matches the detected Plan generation, classification fails closed. This prevents stale trigger material from silently acquiring a current classification.

Each episode may have exactly one classification. Exact idempotent replay returns the original classification; reuse of an idempotency key with different material is rejected.

## Event lineage and persistence

Migration 046 creates:

```text
mission_adaptation_trigger_classifications
```

A new successful classification appends exactly one:

```text
MISSION_ADAPTATION_TRIGGER_CLASSIFIED
```

Repository reconstruction verifies the classification contract hash, source Stage-3.7.1 contract hash, source Plan binding, detection event, classification event payload, record counts, persistence manifest, and store integrity.

## API surface

```text
POST /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/classification
GET  /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/classification
GET  /api/missions/{mission_id}/adaptation-trigger-classifications
GET  /api/missions/{mission_id}/adaptation-trigger-classifications/{classification_id}
GET  /api/missions/{mission_id}/adaptation-trigger-classification-definition
```

## Authority boundary

Stage 3.7.2 **does perform classification**. It does not perform or imply:

```text
replanning eligibility evaluation
ReplanSnapshot binding
Stage-3.2 lifecycle REPLAN
planner invocation
ReplanCandidate creation
Plan delta generation
successor-Plan validation
replan decision/commit
Plan supersession
historical Plan mutation
Mission state transition
terminal-state reopening
Governance authorization query
runtime-control query or I/O
dispatch / execution attempt creation
external network I/O
target action dispatch
target actuation
```

The next planned control is **Stage 3.7.3**.

## Build validation status

The packaged build has been validated in the build sandbox with:

```text
python -m compileall -q mission_orchestrator tests                     PASS
python -m pytest --collect-only -q                                     1197 tests collected
python -m pytest -q tests/test_stage3_7_2_adaptation_trigger_detection_classification.py
                                                                        22 passed
Stage-3.5.10 + Stage-3.4.10 current-head tail probes                   2 passed
```

A complete 1197-test regression is not claimed from the build sandbox because broad/full-suite runs exceeded the available command window before pytest produced a final summary. `STAGE3_7_2_ACCEPTANCE.ps1` is the authoritative target-host gate and requires the entire regression to pass.

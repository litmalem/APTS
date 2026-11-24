# Stage 3.7.3 — Replan Eligibility & Governance Gate

## Purpose

Stage 3.7.3 advances the Stage-3.7 adaptation/replanning pipeline from an immutable Stage-3.7.2 trigger classification to a **fail-closed replan-eligibility decision bound to authoritative Governance**.

The stage answers two bounded questions only:

1. Does the current canonical Mission/Plan/Governance state still satisfy the static preconditions required to evaluate replanning eligibility?
2. Does the authoritative Governance control plane authorize `AUTHORIZE_REPLAN` for this exact adaptation episode under the current immutable scope/binding?

Stage 3.7.3 materializes a durable immutable eligibility/governance gate. It does **not** issue lifecycle `REPLAN`, bind a ReplanSnapshot, invoke the planner, create a successor Plan, compute a Plan delta, validate or commit a replan, supersede a Plan, dispatch work, or actuate a target.

## Runtime identity

```text
control_version = stage3.7.3-replan-eligibility-governance-gate
server_version  = APTSMissionOrchestrator/3.7.3
repository_migration_level = 47
migration = migrations/047_stage3_7_3_replan_eligibility_governance_gate.sql
persistence_store = mission_replan_eligibility_governance_gates
```

Predecessor contracts remain independent and immutable:

```text
Stage 3.7.1 migration metadata = 45
Stage 3.7.1 store              = mission_adaptation_replan_contracts
Stage 3.7.1 persisted state    = DETECTED

Stage 3.7.2 migration metadata = 46
Stage 3.7.2 store              = mission_adaptation_trigger_classifications
Stage 3.7.2 persisted status   = CLASSIFIED
```

## Eligibility/governance contract

```text
stage schema    = apts-replan-eligibility-governance-gate-v1
contract schema = apts-replan-eligibility-governance-contract-v1
identity prefix = rpelig-
event           = MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED
mode            = STATIC_REPLAN_ELIGIBILITY_PLUS_AUTHORITATIVE_GOVERNANCE_FAIL_CLOSED_NO_REPLAN_COMMAND_NO_PLANNER_NO_SUPERSESSION_NO_ACTUATION
authority       = MISSION_ORCHESTRATOR_WITH_EXTERNAL_APTS_GSS
```

Eligibility statuses are closed to:

```text
ELIGIBLE
NOT_ELIGIBLE
REVIEW_REQUIRED
```

A gate is canonically hashed and binds the exact:

- Mission ID;
- Stage-3.7.1 AdaptationEpisode (`adpt-*`) and ReplanTrigger (`rpln-*`);
- Stage-3.7.1 immutable contract hash and detection event;
- Stage-3.7.2 classification (`rcls-*`), immutable classification hash, and classification event;
- current Mission state/version vector;
- current active Stage-3.3 Plan-version head;
- current Mission scope snapshot and scope hash;
- current Governance binding snapshot/version/hash;
- bound authoritative Governance scope-contract hash;
- authoritative Governance PolicyDecision;
- deterministic request fingerprint and operation ID.

## Static fail-closed gate

Before any Governance authorization query, Stage 3.7.3 verifies all local/canonical prerequisites. The static gate requires, among other things:

```text
valid Stage-3.7.1 contract
valid Stage-3.7.2 classification contract
source episode still DETECTED
classification still CLASSIFIED and evidence-backed
exact detection-event binding
exact classification-event binding
Mission state is allowed for adaptation/replanning
Mission state/version unchanged since detection/classification
active Plan contract is valid
active Plan head still matches Stage-3.7.1/3.7.2 bindings
current Mission scope is valid
current Governance binding is valid
Governance binding still belongs to the current Mission scope
Mission ROE allows INTERNAL_REASONING
```

Any failed precondition stops processing **before** the authoritative Governance query.

## Authoritative Governance gate

After static eligibility passes, Mission Orchestrator verifies that the external Governance scope still matches the immutable local Governance binding and submits the bounded authorization request:

```text
authority     = aptsGSS
action_class  = INTERNAL_REASONING
action_name   = AUTHORIZE_REPLAN
resource_type = MISSION
resource      = <mission_id>
purpose       = REPLAN_ELIGIBILITY_ONLY
```

The Governance request context explicitly states that no lifecycle REPLAN, planner invocation, Plan supersession, dispatch, or actuation is being requested by Stage 3.7.3.

### Decision mapping

```text
Governance ALLOW + requires_human_approval=false -> ELIGIBLE
Governance DENY                                  -> NOT_ELIGIBLE
Governance REVIEW                                -> REVIEW_REQUIRED
Governance ALLOW + requires_human_approval=true  -> REVIEW_REQUIRED
```

`ELIGIBLE` means only that the current adaptation episode has passed Stage-3.7.3 eligibility/governance control. It is **not** a lifecycle `REPLAN` command and is not authorization for planner/target side effects outside this stage boundary.

## Idempotency and recovery

Each adaptation episode may have exactly one Stage-3.7.3 gate. Exact replay of the same idempotency material returns the durable gate. Reuse of an idempotency key with different material fails closed.

A deterministic `rpelig-op-*` operation identity is embedded in the Governance authorization context. If the authoritative Governance decision succeeded but the local response was lost before persistence, Stage 3.7.3 can recover the matching Governance PolicyDecision by mission correlation and persist the same logical operation rather than issuing a duplicate authorization request.

## Event lineage and persistence

Migration 047 creates:

```text
mission_replan_eligibility_governance_gates
```

A successful new gate appends exactly one canonical Mission event:

```text
MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED
```

Repository reconstruction/integrity verifies the Stage-3.7.3 contract hash, Stage-3.7.1/3.7.2 source bindings, Mission scope and Governance binding hashes, authoritative Governance scope hash, PolicyDecision fields, Mission event binding/cardinality, record counts, and persistence manifest.

## API surface

```text
POST /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/eligibility
GET  /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/eligibility
GET  /api/missions/{mission_id}/replan-eligibility-gates
GET  /api/missions/{mission_id}/replan-eligibility-gates/{eligibility_gate_id}
GET  /api/missions/{mission_id}/replan-eligibility-governance-definition
```

No Stage-3.7.3 HTTP surface exists for planner invocation, replan commit, Plan supersession, dispatch, or target action.

## Authority boundary

Stage 3.7.3 **does perform**:

```text
static replan-eligibility verification
authoritative Governance scope verification
authoritative Governance authorization query
immutable PolicyDecision binding
durable eligibility/governance gate persistence
canonical Mission event recording
```

Stage 3.7.3 does **not** perform:

```text
Stage-3.2 lifecycle REPLAN
ReplanSnapshot binding
planner invocation
ReplanCandidate creation
Plan delta generation
successor-Plan validation
replan decision/commit
Plan supersession
historical Plan mutation
Mission state transition
runtime-control I/O
dispatch / execution-attempt creation
external target network I/O
target-action dispatch
target actuation
```

The next planned control is **Stage 3.7.4**.

## Build validation status

The packaged build has been validated in the build sandbox with:

```text
python -m compileall -q mission_orchestrator tests                     PASS
python -m pytest --collect-only -q                                     1216 tests collected
python -m pytest -q tests/test_stage3_7_3_replan_eligibility_governance_gate.py
                                                                        19 passed
Stage 3.1 aggregate                                                    111 passed
Stage 3.2 split regression                                             156 passed
Stage 3.3 split regression                                             239 passed
Stage 3.5.10 / 3.6.10 closure suites                                  12 + 12 passed
Stage 3.7.1 / 3.7.2 predecessor focused suites                        19 + 22 passed
Historical current-head tail probes                                    2 passed
```

A complete 1216-test monolithic regression is **not claimed** from the build sandbox. The broad run exceeded the execution window before pytest emitted a final summary. `STAGE3_7_3_ACCEPTANCE.ps1` is therefore the authoritative target-host acceptance gate and requires the complete regression to pass before Stage 3.7.3 is recorded as accepted.

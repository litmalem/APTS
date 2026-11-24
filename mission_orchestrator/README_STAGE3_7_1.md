# Stage 3.7.1 — Canonical Adaptation / Replan Contract & Identity

## Purpose

Stage 3.7.1 opens **Stage 3.7 — Adaptation / Replanning** by introducing the canonical, immutable identity layer for an adaptation episode and its triggering reason. The stage records that the currently active Mission/Plan trajectory has produced a condition that may require adaptation, while deliberately stopping before classification, eligibility, lifecycle REPLAN transition, planner execution, successor-Plan creation, validation, commit, or handoff.

The resulting contract provides a durable point from which later Stage-3.7 controls can reason deterministically about *why* replanning was considered, *which* Mission state and active Plan were observed, and *which* Plan generation would be the next generation if a later authority actually commits replanning.

## Runtime identity

```text
control_version = stage3.7.1-canonical-adaptation-replan-contract-identity
server_version  = APTSMissionOrchestrator/3.7.1
repository_migration_level = 45
migration = migrations/045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql
persistence_store = mission_adaptation_replan_contracts
```

## Canonical identities

Stage 3.7.1 materializes only these identities:

```text
AdaptationEpisode  prefix = adpt-
ReplanTrigger      prefix = rpln-
```

The following namespaces are reserved for later stages but are **not** materialized by Stage 3.7.1:

```text
ReplanSnapshot     prefix = rpsnap-
ReplanCandidate    prefix = rpcand-
ReplanDecision     prefix = rpdec-
ReplanCommit       prefix = rpcom-
```

## Contract identity

```text
stage schema   = apts-adaptation-replan-contract-identity-v1
contract schema= apts-canonical-adaptation-replan-contract-v1
mode           = IMMUTABLE_ADAPTATION_EPISODE_AND_REPLAN_TRIGGER_IDENTITY_BOUND_TO_CURRENT_NONTERMINAL_MISSION_AND_ACTIVE_PLAN_PENDING_CLASSIFICATION
authority      = MISSION_ORCHESTRATOR_ADAPTATION_REPLAN_MATERIALIZATION
initial state  = DETECTED
```

The canonical future episode-state model is declared as:

```text
DETECTED
  -> CLASSIFIED
  -> ELIGIBILITY_PENDING
  -> ELIGIBLE
  -> SNAPSHOT_BOUND
  -> REPLAN_REQUESTED
  -> CANDIDATE_READY
  -> VALIDATED
  -> COMMITTED
  -> HANDOFF_READY
```

Stage 3.7.1 itself stops at `DETECTED`.

## Source-state and Plan binding

A detection can be materialized only while the Mission is in one of the canonical non-terminal states from which Stage 3.2 permits REPLAN semantics:

```text
RUNNING
WAITING_EVIDENCE
WAITING_APPROVAL
```

The request is concurrency-bound to the exact current Mission version/state and exact active Stage-3.3 Plan head. If the active Plan is generation `N`, the immutable detection contract records:

```text
source_plan_generation = N
target_plan_generation = N + 1
```

This is an **intent/binding rule**, not successor-Plan creation. Historical Plans remain immutable and the active Plan is not superseded in Stage 3.7.1.

A Mission already in `REPLANNING` is rejected to avoid duplicate adaptation-episode semantics. Terminal Missions are rejected and cannot be reopened.

## Trigger contract

Supported trigger sources:

```text
MISSION_EVENT
OPERATOR_REQUEST
SYSTEM_OBSERVATION
EXTERNAL_SIGNAL
```

Canonical trigger codes:

```text
CTI_CHANGE
TASK_FAILURE
TASK_TIMEOUT
AUTHORIZATION_REVOCATION
MISSION_STATE_CHANGE
EVIDENCE_CHANGE
PIP_CHANGE
DEPENDENCY_CHANGE
POLICY_CHANGE
RESOURCE_CHANGE
OPERATOR_INTERVENTION
OTHER
```

A `MISSION_EVENT` trigger binds the exact canonical source event ID and SHA-256. Non-event triggers require explicit evidence references. Requests use an idempotency key and optimistic-concurrency bindings; replaying the exact same request returns the same episode/trigger identities and does not duplicate the detection event.

## Event lineage

Creation of a new episode appends exactly one canonical Mission event:

```text
MISSION_ADAPTATION_REPLAN_DETECTED
```

The event is causally bound to the `adaptation_episode_id`. Repository reconstruction verifies the persisted contract, source Plan binding, optional source-event binding, detection-event lineage, record counts, and canonical hashes.

## API surface

```text
POST /api/missions/{mission_id}/adaptation-replans
GET  /api/missions/{mission_id}/adaptation-replans
GET  /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}
GET  /api/missions/{mission_id}/adaptation-replan-definition
```

Creation returns HTTP `201`; an exact idempotent replay returns HTTP `200`.

## Authority boundary

Stage 3.7.1 performs **materialization only**. It does not:

```text
classify the trigger
perform replanning-eligibility evaluation
bind a ReplanSnapshot
issue the Stage-3.2 REPLAN lifecycle command
invoke the planner
create a ReplanCandidate
compute a Plan delta
validate a successor Plan
commit a successor Plan
supersede the active/historical Plan
transition Mission lifecycle state
query Governance or runtime controls
perform dispatch or create an execution attempt
perform external network I/O
send a target action
actuate a target
reopen a terminal Mission
```

This separation keeps Stage 3.7.1 compatible with the existing authority boundaries: Stage 3.2 owns lifecycle transitions, Stage 3.3 owns Plan generation/versioning, Stage 3.4 owns routing/delegation, Stage 3.5 owns dispatch/execution, and Stage 3.6 owns outcome/completion semantics.

## Persistence

Migration 045 creates:

```text
mission_adaptation_replan_contracts
```

The table durably stores the immutable adaptation/replan contract, identity pair, source Mission/Plan concurrency bindings, trigger/evidence bindings, canonical/request hashes, idempotency key, episode state, and detection metadata. The store is included in repository record counts, persistence manifests, and integrity reconstruction.

## Validation status for this build

```text
python -m compileall -q mission_orchestrator tests             PASS
python -m pytest --collect-only -q                             1175 tests collected
focused Stage 3.7.1                                            19 passed
historical Stage 3.5.10 + 3.4.10 current-head tail probes      2 passed
```

The complete regression suite is intentionally **not claimed as PASS in the build sandbox** because full-suite attempts exceeded the available command window before pytest emitted a final summary. `STAGE3_7_1_ACCEPTANCE.ps1` is therefore the authoritative target-host gate and requires the complete 1175-test regression to pass before Stage 3.7.1 is recorded as accepted.

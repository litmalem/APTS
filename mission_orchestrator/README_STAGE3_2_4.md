# Stage 3.2.4 — Planning and Run Activation (`PIP_BOUND → PLANNING → RUNNING`)

Stage 3.2.4 turns the next two operational lifecycle edges into an explicit **Planning and Run Activation Contract**. It does not implement an autonomous planner and it does not authorize target execution. Instead, it proves that Mission lifecycle progression follows the durable activation lineage established by Stage 3.2.3 and Stage 3.2.4 itself.

## Planning/run activation contract

Schema: `apts-mission-planning-run-activation-v1`

Mode: `PIP_BOUND_TO_PLANNING_TO_RUNNING_WITH_LOCAL_LINEAGE_PROOFS`

Planning activation:

- command: `START_PLANNING`
- transition: `PIP_BOUND -> PLANNING`
- prerequisite: valid Stage-3.2.3 `CREATED -> PIP_BOUND` activation evidence tied to the current immutable Mission envelope and exact `pip_id + pip_version`.

Initial run activation:

- command: `START`
- transition: `PLANNING -> RUNNING`
- prerequisite: valid Stage-3.2.4 `PIP_BOUND -> PLANNING` activation evidence, which itself is chained to the Stage-3.2.3 PIP activation proof.

The lifecycle phase chain is therefore:

`CREATED --BIND_PIP--> PIP_BOUND --START_PLANNING--> PLANNING --START--> RUNNING`

A topology-valid state created through the legacy direct transition API is not sufficient to pass the Stage-3.2.4 lifecycle command guard if the required activation lineage is absent.

## Read API

`GET /api/missions/{mission_id}/planning-run-activation-contract`

The projection exposes:

- current planning/run activation readiness;
- Stage-3.2.3 PIP activation proof status;
- Stage-3.2.4 planning activation proof status;
- Stage-3.2.4 run activation proof status;
- complete activation-chain status;
- exact immutable PIP identity/version and canonical envelope hash;
- explicit no-planner/no-plan-artifact/no-Governance/no-execution semantics.

The existing lifecycle discovery endpoint also embeds the same `planning_run_activation` projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

## START_PLANNING execution

A successful `START_PLANNING` still passes through:

1. Stage-3.1.6 version-vector and idempotency command gate;
2. Stage-3.2.2 lifecycle command/source/topology/PIP guard matrix;
3. Stage-3.2.4 lineage guard requiring valid Stage-3.2.3 PIP activation evidence.

Successful responses include `planning_run_activation` evidence with phase `PLANNING`. The evidence is also embedded in transition metadata and therefore becomes durable through the existing append-only state transition ledger.

`START_PLANNING` **does not invoke a planner** and **does not create a plan artifact** in Stage 3.2.4. It activates the Mission lifecycle planning phase only.

## Initial START execution

The initial `START` from `PLANNING` requires durable Stage-3.2.4 planning activation evidence. Successful responses include `planning_run_activation` evidence with phase `RUNNING`, chained to both the PIP activation transition and the planning activation transition.

Entering Mission state `RUNNING` is explicitly **not** equivalent to target-execution authorization. Stage 3.2.4 does not query Governance, does not synthesize `ALLOW`, does not dispatch a target action, and does not actuate against a target.

`START` from later states such as `WAITING_EVIDENCE`, `WAITING_APPROVAL`, or `REPLANNING` is not reclassified as an initial Stage-3.2.4 run activation. Dependency satisfaction and richer return-to-running semantics remain deferred to later lifecycle stages.

## Guard-matrix extension

Stage 3.2.4 adds local guard checks:

- `PIP_ACTIVATION_EVIDENCE_FOR_PLANNING`
- `PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN`
- `CANONICAL_ENVELOPE_INTEGRITY_FOR_PLANNING_RUN_ACTIVATION`

These guards are local Mission lifecycle controls. They perform no external authority query and synthesize no Governance decision.

## Authority boundary

Stage 3.2.4 deliberately does not:

- invoke an autonomous planner;
- create a canonical plan artifact;
- query or replace aptsGSS Governance authority;
- grant authorization;
- dispatch target actions;
- actuate against a target;
- add a database migration;
- introduce a new event type;
- implement Stage-3.2.5 evidence/approval dependency resolution;
- implement Stage-3.2.8 verified completion gate.

Governance remains `EXTERNAL_APTS_GSS`. Repository migration level remains **8**.

## Regression baseline

`166 passed`.

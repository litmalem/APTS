# Stage 3.9.1 — Canonical E2E Mission Scenario & Acceptance Contract

Stage 3.9.1 opens the end-to-end qualification track after Stage 3.8 has closed observability and reconstruction. Its purpose is deliberately narrow: **freeze one canonical Mission scenario and one versioned acceptance contract before any Stage 3.9 segment is executed**.

The active runtime control becomes `stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract`. Repository migration remains **53**. No new durable store is introduced.

## What Stage 3.9.1 adds

The implementation adds `mission_orchestrator/e2e_mission_acceptance.py`, which owns:

- acceptance schema `apts-stage3.9-e2e-mission-acceptance-contract-v1`;
- scenario schema `apts-stage3.9-canonical-e2e-mission-scenario-v1`;
- canonical scenario ID `stage3.9-canonical-e2e-control-plane-mission-v1`;
- the Stage 3.1–3.8 closure controls that must already be present;
- the frozen Stage 3.9.1–3.9.10 qualification sequence;
- cross-stage identity families used to prove lineage from Mission intake through planning, routing/delegation, execution, outcome, adaptation/replanning, and forensic reconstruction;
- success, failure, and fail-closed invariants;
- a deterministic control-plane Mission request template that can be materialized with a bounded `run_id` without creating or executing a Mission;
- an integrity digest that makes the acceptance contract immutable and version-bound.

A new read-only route is available at:

`GET /api/e2e/mission-scenario-acceptance-contract`

The route returns the Stage 3.9.1 definition and the complete canonical contract. Repeated reads are deterministic and introduce no Mission record, state transition, Governance query, routing, delegation, dispatch, execution attempt, external network I/O, telemetry export, target actuation, durable store, or database migration.

## Canonical scenario boundary

The scenario is intentionally a **control-plane sandbox**. It freezes the Mission request and E2E acceptance semantics while leaving execution of the scenario to later Stage 3.9 substages. The request is bound to low-risk acceptance semantics, a fixed scenario ID, CTI as the required subsystem, existing scope/PIP/policy version bindings, explicit success criteria, and `external_target_actuation_allowed = false`.

Only two run-specific fields may change when the template is materialized: the idempotency key and `metadata.run_id`. All semantic Mission fields remain invariant.

## Acceptance invariants

The contract requires one canonical Mission root across the complete trajectory; source-bound lineage across plan/task/route/delegation/dispatch/execution/outcome/replan identities; Governance authorization before delegation and authoritative pre-dispatch revalidation; evidence binding before completion; dependency-aware completion before Mission outcome aggregation; verified success before completion handoff; replay/recovery without duplicate side effects; read-only observe/reconstruct views; and fail-closed behavior for tamper, gaps, or source drift.

Stage 3.9.1 itself **does not grant new authority**. In particular, it adds no Governance, routing, delegation, dispatch, execution, target-actuation, external-I/O, telemetry, persistence, or database-migration authority. Runtime acceptance remains externally executed by the acceptance harness; the runtime does not self-certify.

## Qualification

`STAGE3_9_1_ACCEPTANCE.ps1` verifies runtime activation and boundary fields, checks the deterministic contract route, compiles Python, requires the exact **1443-test** inventory, executes the complete Stage 3.1–3.9.1 regression, runs the **12 focused Stage 3.9.1 tests**, and re-runs the **4 Stage 3.8.10 closure tests**.

The next implementation stage is **3.9.2 — Intake → Lifecycle E2E segment qualification**. It must execute the relevant portion of the frozen 3.9.1 scenario rather than redefining the scenario contract.

# Stage 3.9.2 — Intake → Lifecycle E2E Segment Qualification

Stage 3.9.2 executes and qualifies the first runtime segment of the canonical Stage 3.9 scenario frozen by Stage 3.9.1. It deliberately **reuses the Stage 3.9.1 Mission request and existing Mission intake/lifecycle authorities** rather than creating a second scenario definition or a new execution path.

The active runtime control becomes `stage3.9.2-intake-lifecycle-e2e-segment-qualification`. Repository migration remains **53** and no new durable store is introduced.

## Qualified segment

The canonical segment is frozen as:

`Mission intake → CREATED(v1) → BIND_PIP → PIP_BOUND(v2) → START_PLANNING → PLANNING(v3)`

`PLANNING` state version **3** is the exact Stage 3.9.2 segment head. Stage 3.9.2 does **not** invoke the planner and does **not** materialize a plan or task graph. Those domains remain outside this stage and are handed to Stage 3.9.3.

The exact expected lifecycle footprint at the qualified head is:

- 1 canonical Mission;
- 1 canonical Mission envelope;
- 1 current Mission state;
- 2 state transitions;
- 2 completed lifecycle-command journal entries;
- 5 Mission events, in order:
  1. `MISSION_REGISTERED`
  2. `MISSION_STATE_TRANSITIONED`
  3. `MISSION_COMMAND_COMPLETED`
  4. `MISSION_STATE_TRANSITIONED`
  5. `MISSION_COMMAND_COMPLETED`.

Exact replay of Mission creation, `BIND_PIP`, and `START_PLANNING` must be idempotent and must not add transitions, commands, or events.

## What Stage 3.9.2 adds

The implementation adds `mission_orchestrator/e2e_intake_lifecycle_qualification.py`, which owns:

- qualification schema `apts-stage3.9-intake-lifecycle-segment-qualification-v1`;
- an integrity-bound qualification contract linked to the Stage 3.9.1 acceptance-contract SHA-256;
- the exact `BIND_PIP` / `START_PLANNING` command and state-version sequence;
- the expected Mission-event sequence and repository footprint;
- deterministic Stage 3.9.2 command construction;
- fail-closed verification that the Mission envelope still matches the frozen Stage 3.9.1 request semantics;
- exact transition, command, event, identity, activation, and Mission-root lineage checks;
- a read-only runtime verifier that returns `QUALIFIED` only when all segment invariants hold.

Two read-only routes are added:

- `GET /api/e2e/intake-lifecycle-qualification-contract`
- `GET /api/missions/{mission_id}/e2e-intake-lifecycle-qualification`

The contract route is deterministic. The Mission qualification route reads existing durable evidence only; repeated reads do not mutate Mission state or repository records.

## Authority boundary

Stage 3.9.2 adds **no new operational authority**. The acceptance harness uses the already-existing public Mission intake and lifecycle-command routes. The runtime verifier itself is read-only.

No new Governance, routing, delegation, dispatch, execution, planner, external-network-I/O, telemetry-export, or target-actuation authority is introduced. No database migration or new durable store is added.

The focused tests also inject fail-fast external clients, proving that the qualified intake/lifecycle segment does not require Governance or CTI network calls. The `START_PLANNING` result must explicitly show `planner_invocation_performed = false`, `plan_artifact_created = false`, and `execution_authorized = false`.

## Qualification and regression

The canonical pytest inventory increases from **1443** to **1458** tests (+15 Stage 3.9.2 tests).

Local build qualification established:

- Python compilation: PASS;
- canonical inventory: **1458 tests collected**;
- focused Stage 3.9.2: **15/15 PASS**;
- Stage 3.9.1 predecessor: **12/12 PASS**;
- Stage 3.8.10 predecessor: **4/4 PASS**;
- selected identity/state/version/event + lifecycle activation + 3.8.10 + 3.9.1 + 3.9.2 compatibility set: **124/124 PASS**.

A complete 1458-test run is intentionally required on the deployment host by `STAGE3_9_2_ACCEPTANCE.ps1`; the build sandbox did not complete the full suite within its bounded execution window, so a local full-regression PASS is not claimed here.

The next stage is **3.9.3 — Planning → Task Graph E2E Segment Qualification**, starting from the exact qualified head `PLANNING(v3)`.

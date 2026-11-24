# Stage 3.9.3 — Planning → Task Graph → Dependency Verification

Stage 3.9.3 continues the canonical Stage 3.9 end-to-end Mission acceptance trajectory from the exact Stage 3.9.2 head `PLANNING(v3)`. It qualifies the existing Stage 3.3 planning primitives as one deterministic E2E segment:

`PLANNING(v3) → Plan Contract → Planner Input Snapshot → Task Decomposition → Dependency DAG → structural PASS`

The active runtime control is `stage3.9.3-planning-task-graph-dependency-verification`. Repository migration remains **53**. No new durable store or operational authority is introduced.

## Qualified task graph

The canonical Stage 3.9.3 task set contains exactly three CTI tasks:

1. `collect-cti` — collect canonical CTI context.
2. `analyze-cti` — analyze that context.
3. `report-findings` — structure the planning findings.

The dependency graph is frozen as:

`collect-cti → analyze-cti → report-findings`

The graph must contain exactly **3 nodes** and **2 edges**, have no dangling/self/duplicate edges, and validate as a directed acyclic graph. Its canonical topological order is the task order above, with `collect-cti` as the sole root and `report-findings` as the sole leaf.

## Exact qualified head

Stage 3.9.3 deliberately remains in Mission state `PLANNING(v3)`. The qualified head is:

- canonical Plan: version 1;
- planner-input snapshot: version 1;
- task decomposition: version 1;
- planned tasks: 3;
- dependency graph: version 1, `validation_status=PASS`;
- dependency edges: 2;
- planner invocation: **not materialized**;
- generated plan: **not materialized**;
- plan validation/activation/readiness: **not materialized**;
- routing/delegation/governance/dispatch/execution: **not materialized**.

The exact nonzero repository footprint at the qualified head is 1 Mission, 1 envelope, 1 state, 2 lifecycle transitions, 2 command-journal records, 1 Plan, 1 planner-input snapshot, 1 task decomposition, 3 planned tasks, 1 dependency graph, 2 dependency edges, and 9 Mission events.

## Runtime qualification contract

`mission_orchestrator/e2e_planning_task_graph_qualification.py` adds a canonical SHA-256-bound qualification contract and a read-only verifier. It verifies the frozen Stage 3.9.1 Mission semantics, preserves the Stage 3.9.2 lifecycle lineage, verifies every planning artifact and dependency edge, checks exact DAG structure/topology, checks event-chain integrity and repository footprint, and rejects partial or downstream-expanded states.

Read-only routes:

- `GET /api/e2e/planning-task-graph-qualification-contract`
- `GET /api/missions/{mission_id}/e2e-planning-task-graph-qualification`

The acceptance execution itself reuses the already-existing Stage 3.3.1–3.3.4 public mutation routes; Stage 3.9.3 does not create a parallel planning implementation.

## Replay and authority boundary

Exact replay of Plan, snapshot, decomposition, and dependency graph creation must be idempotent. A replay must not duplicate planning artifacts, edges, or Mission events.

Stage 3.9.3 adds no planner invocation authority, governance authority, routing/delegation authority, dispatch/execution authority, target actuation, external network I/O, telemetry export, migration, or new durable store. The acceptance harness can therefore qualify the planning structure without crossing into Stage 3.9.4 or later domains.

## Regression status in the build sandbox

- Python compilation: PASS.
- Canonical inventory: **1473 tests collected**.
- Focused Stage 3.9.3: **15/15 PASS**.
- Stage 3.9.1 + 3.9.2 immediate predecessor set: **27/27 PASS**.
- Stage 3.3.4 dependency-graph structural validation: **29/29 PASS**.
- Stage 3.1 historical set: **111/111 PASS**.
- Stage 3.2 historical set was executed in two bounded chunks: **71/71 PASS** and **85/85 PASS**.

The complete 1473-test regression remains an explicit deployment-host gate in `STAGE3_9_3_ACCEPTANCE.ps1`; the sandbox execution window did not permit one uninterrupted full-suite run, so no local full-suite PASS is claimed.

The next stage is **3.9.4 — Routing → Delegation → Governance**.

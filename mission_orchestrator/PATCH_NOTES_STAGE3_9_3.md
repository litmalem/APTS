# Patch Notes — Stage 3.9.3

## Scope
Implements `3.9.3 — Planning → Task Graph → Dependency Verification` as the third segment of Stage 3.9 E2E Mission acceptance.

## Runtime changes
- Active control: `stage3.9.3-planning-task-graph-dependency-verification`.
- API server version: `APTSMissionOrchestrator/3.9.3`.
- Repository migration: unchanged at `53`.
- Added canonical Stage 3.9.3 qualification contract and read-only verifier.
- Added read-only qualification contract and per-Mission qualification routes.
- Added Stage 3.9.3 health contract fields.
- Reused Stage 3.3.1–3.3.4 Plan/snapshot/decomposition/dependency-graph authorities.

## Canonical E2E planning graph
`collect-cti → analyze-cti → report-findings`

Expected graph: 3 nodes, 2 edges, DAG validation `PASS`.

## Boundaries preserved
No new database migration, durable store, planner invocation, generated plan, readiness projection, routing, delegation, governance decision, dispatch, execution, external I/O, telemetry export, or target actuation authority.

## Tests
Adds 15 Stage 3.9.3 tests; canonical inventory becomes 1473 tests. Historical test expectations were rebased to the Stage 3.9.3 runtime control/API version while preserving Stage 3.9.2 as the semantic predecessor.

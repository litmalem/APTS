# Stage 3.8.3 — Global Causal Lineage Graph

Stage 3.8.3 derives a deterministic, read-only global causal DAG from the Stage 3.8.2 verified normalized Mission event projection. It adds one Mission root node plus one immutable graph node per normalized durable event, preserves parent-event causality, records resolvable event-to-event causation edges, and retains unresolved domain causation IDs as non-authoritative external references.

The graph is integrity hashed at node, edge, and graph levels. Verification rejects dangling edges, integrity tampering, cycles, and nodes that are not reachable from the Mission root. Parent references must resolve to an earlier event in the verified ledger order. Graph construction performs no authorization, Governance query, runtime probe, external network I/O, telemetry export, routing, delegation, dispatch, execution attempt, Mission lifecycle transition, target action, or target actuation.

Runtime control: `stage3.8.3-global-causal-lineage-graph`. Server: `APTSMissionOrchestrator/3.8.3`. Repository migration remains 53; no durable graph store is added.

Read APIs:
- `GET /api/missions/{mission_id}/observability-causal-graph`
- `GET /api/observability/causal-graph-contract`

Canonical test inventory after this patch is 1382 tests. The authoritative deployment-host gate is `STAGE3_8_3_ACCEPTANCE.ps1`.

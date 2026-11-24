# Stage 3.9.9 patch notes

- Added SHA-256-bound **Global Observation / Reconstruction / Forensic Equivalence** contract and pure evaluator.
- Binds directly to the qualified Stage 3.9.8 restart/replay/recovery head at repository migration level **53**.
- Requires the canonical 50-event Mission ledger to equal the 50 normalized events and 50 deterministic timeline event references.
- Requires the global causal graph to contain exactly **51 nodes / 50 edges** for the canonical Stage 3.9.8 head.
- Cross-checks independently rebuilt normalized events, causal graph, decision trace, timeline, and live projection against the exact sources embedded in one verified Stage 3.8.9 forensic bundle.
- Verifies the forensic bundle records bind the exact durable Mission events, mission state, active Plan v2, and repository footprint.
- Derives reconstruction and event/lineage/integrity forensic queries from the same verified forensic snapshot and requires exact equality with the corresponding direct observability views.
- Requires global trace identity and canonical event-tip hash equivalence across observation, reconstruction, and forensic surfaces.
- Requires integrity diagnostics `PASS`, zero blocking findings, and observability health `HEALTHY`.
- Adds fail-closed negative coverage for cross-view drift and canonical-event tampering.
- Adds read-only contract/qualification routes and Stage 3.9.9 health declarations.
- Explicitly preserves the boundary: forensic bundle is not external attestation; reconstruction is not runtime resumption, mission re-execution, or integrity repair.
- No new database migration, durable store, observation authority, forensic authority, governance/runtime query, dispatch, execution attempt, lifecycle transition, external network I/O, or target actuation is introduced.
- Rebases historical current-control/server-version assertions to Stage 3.9.9 while retaining Stage 3.9.8 in ordered supported-control history.
- Canonical test inventory becomes **1560**; focused Stage 3.9.9 suite has **15 tests**.

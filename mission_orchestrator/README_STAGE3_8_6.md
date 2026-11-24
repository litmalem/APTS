# Stage 3.8.6 — Deterministic Mission Timeline Reconstruction

Stage 3.8.6 reconstructs a Mission timeline on demand from the verified Stage 3.8.2 normalized event ledger, the Stage 3.8.3 global causal graph, and the Stage 3.8.5 decision/governance/evidence trace. Every ledger event is represented exactly once, in durable append order, with a deterministic entry identity, its causal node and parent, source event hash, recorded UTC timestamp, version observations, and any existing decision trace categories.

Source timestamps are observations, not causal ordering authority. Equal timestamps remain separate entries. If a later ledger event has an earlier timestamp, the timeline preserves append order, records a signed delta in microseconds, and reports `OBSERVED_TIMESTAMP_BACKWARD`. Unresolved external causation IDs remain labeled as external references. The decision trace's categories are historical annotations and never grant authority.

The builder rejects corrupted normalized event hashes, cross-Mission/trace input, graph/ledger mismatches, invalid graph or decision trace integrity, missing causal links, forward parent/causation references, and annotation/source mismatches. The projection and every entry have domain-separated SHA-256 integrity digests. These digests allow comparison and tamper detection of the read result; they are not signatures from an external authority.

Runtime control: `stage3.8.6-deterministic-mission-timeline-reconstruction`. HTTP server: `APTSMissionOrchestrator/3.8.6`. Repository migration remains **53**; no new durable store or migration is introduced.

Read APIs:

- `GET /api/missions/{mission_id}/observability-timeline`
- `GET /api/observability/timeline-contract`

The timeline is read only. Its construction performs no authorization, Governance query, runtime probe, external network I/O, telemetry export, routing, delegation, dispatch, execution attempt creation, Mission state transition, target action, or target actuation. The service reads existing stores through the existing verified projection methods; it does not make a new point-in-time database snapshot across those methods. Concurrent writes during a read can cause a source binding mismatch and fail the projection; a subsequent read can succeed once the source view is stable.

The Stage 3.8.6 patch is an **overlay** for the Stage 3.8.5 source package supplied on 24 September 2026. It contains only changed source and test files, this description, the acceptance script, and installation instructions. The deployment database and previous migrations are not part of the patch.

After applying the patch and restarting the server, run `STAGE3_8_6_ACCEPTANCE.ps1` from `D:\mission_orchestrator`. For an existing Mission, pass `-MissionId` to also check the live timeline route. The acceptance script requires the exact canonical regression inventory and full test pass reported in this package; execution on the Windows deployment host remains the authoritative runtime acceptance.

Local source verification (Python 3.12, SQLite): **1,397 passed in 1,013.17 seconds**. Focused timeline regression: **5 passed**. HTTP smoke check: timeline contract 200, existing Mission timeline 200, unknown Mission 404. Windows deployment acceptance has not been run in this workspace.

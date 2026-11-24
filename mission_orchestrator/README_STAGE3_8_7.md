# Stage 3.8.7 — Integrity, Gap & Consistency Diagnostics

The Stage 3.8.7 read API derives a deterministic diagnostic report for one Mission from the verified normalized event ledger and the existing causal graph, decision/governance/evidence trace, timeline, and live state projection. It verifies each source independently and compares the relationships between sources. A report contains source statuses, stable findings, a summary status, and a domain-separated SHA-256 digest. The digest detects accidental/tampered read results, but is not a signature from an external authority.

Categories:

| Category | Examples | Effect |
| --- | --- | --- |
| `INTEGRITY` | Invalid source digest/scope, duplicate ledger event, unavailable verified source | Blocking finding |
| `GAP` | Missing registration event, parent event, causal node, timeline event or decision annotation | Blocking finding |
| `CONSISTENCY` | A digest-valid graph, timeline, decision trace or live head disagreeing with the ledger or their bound sources | Blocking finding |
| `OBSERVATION` | Unresolved **external** causation reference, backward source timestamp | Informational finding; does not by itself degrade `PASS` |

`status=PASS` means no blocking findings and all sources available. `FINDINGS` means a blocking finding exists with all sources available. `INDETERMINATE` means at least one required source could not be read; known gaps remain in the report. The wrapper's `integrity_status=PASS` means the *diagnostic report itself* passed its own verifier, not that its sources or Mission passed. Use `diagnostics.status` and `diagnostics.source_status` for source health.

Read APIs:

- `GET /api/missions/{mission_id}/observability-diagnostics`
- `GET /api/observability/diagnostics-contract`

Runtime control: `stage3.8.7-integrity-gap-consistency-diagnostics`; HTTP server `APTSMissionOrchestrator/3.8.7`. Repository migration remains **53**. The report is read only and adds no durable store. It makes no Governance query, authorization decision, runtime probe, network request, telemetry export, routing, delegation, dispatch, execution attempt, Mission state transition, or target action.

The service reuses Stage 3.8.2–3.8.6 verified source reads. These reads are not one atomic database snapshot; concurrent source writes can yield `FINDINGS` or `INDETERMINATE`. Retry after writers settle before interpreting a cross-source discrepancy. A broken authoritative Mission envelope still fails closed; an unknown Mission returns 404. No diagnostic finding repairs a source or grants authority.

All projections ultimately use local canonical stores. Without an independent external checkpoint, they cannot prove that a fully consistent tail of events was never removed. Hashes and cross-source checks should therefore be interpreted within that source boundary.

The patch overlays a Stage 3.8.6 installation. The patch includes source and rebased tests, this description, the acceptance script, instructions, and a SHA-256 manifest. It contains no `data/` directory or migration. Run `STAGE3_8_7_ACCEPTANCE.ps1` after restarting the Windows service; optionally pass `-MissionId` to check an existing Mission.

Local verification on Python 3.12 / SQLite (25 September 2026 UTC): compilation passed, **1,408 collected**, **1,408 passed in 953.35 seconds**, and **11 focused Stage 3.8.7 tests passed**. The focused suite covers HTTP contract and Mission routes (including 404), restart stability, read-only behavior, corrupt/unavailable sources, source gaps, digest-valid cross-source mismatches, and report tampering. Windows deployment acceptance has not been run in this workspace.

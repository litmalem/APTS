# VulnDesk / aptsGSS Stage 2.9.6 — Health / Diagnostics

## Goal

Stage 2.9.6 converts the Stage 2.9.x observability primitives into explicit, read-only
runtime readiness and mission diagnostics. It does not alter authorization, TaskContract,
PolicyDecision, lineage, revocation, or integrity evidence.

## Control version

VulnDesk:

`hybrid-event-driven-2.17-health-diagnostics`

Diagnostic schema:

`cti-health-diagnostics-v1`

Governance diagnostic schema:

`governance-health-diagnostics-v1`

## VulnDesk additions

New module:

`cti_services/diagnostics.py`

New endpoints:

- `GET /api/cti/diagnostics`
- `GET /api/cti/diagnostics?deep=true`
- `GET /api/cti/missions/{mission_id}/diagnostics`

`GET /health` now includes:

- `diagnostics_mode`
- `readiness_status`
- `diagnostic_summary`

Shallow runtime checks:

1. `DATABASE_CONNECTIVITY` — mandatory;
2. `EVENT_DISPATCHER` — mandatory;
3. `EVENT_QUEUE_BACKLOG` — operational warning/failure thresholds;
4. `CANONICAL_LINEAGE_SCHEMA` — mandatory Stage 2.9 schema readiness;
5. `INTEGRITY_PROBE_CAPABILITY` — mandatory Stage 2.9.5 capability;
6. `GOVERNANCE_CONFIGURATION` — dependency/configuration observation.

Deep diagnostics additionally calls the external authoritative Governance `/health`
endpoint and reports `GOVERNANCE_REACHABILITY`. A Governance outage never fabricates
an ALLOW or changes policy state; it only degrades readiness.

Mission diagnostics summarize the already-existing canonical projection, Governance
correlation and Stage 2.9.5 integrity result. They do not reroute or repair mission state.

## Governance additions

New module:

`app/diagnostics.py`

New endpoint:

- `GET /api/governance/diagnostics`
- `GET /api/governance/diagnostics?deep=true`

`GET /health` now exposes the same readiness semantics while preserving the existing
health contract fields.

Governance checks:

1. `DATABASE_CONNECTIVITY` — mandatory;
2. `OUTBOX_WORKER` — mandatory;
3. `OUTBOX_DELIVERY_STATE` — failed delivery warning;
4. `EMERGENCY_STOP_STATE` — active emergency-stop is surfaced explicitly;
5. `CTI_RUNTIME_REACHABILITY` — deep-only dependency check.

The deep Governance dependency check points to VulnDesk `/health`. VulnDesk shallow
health does not call Governance, so there is no cyclic deep health dependency.

## Status semantics

Runtime health:

- `HEALTHY` / `READY`: all mandatory checks pass and no warnings exist;
- `DEGRADED`: mandatory checks pass but one or more warnings/non-mandatory failures exist;
- `UNHEALTHY` / `NOT_READY`: at least one mandatory check fails.

Mission diagnostics:

- `HEALTHY`: canonical projection + correlated governance + PASS integrity;
- `DEGRADED`: incomplete/unverifiable observability evidence;
- `VIOLATION_DETECTED`: Stage 2.9.5 reports an evidence-backed integrity violation.

## Database migration

None required.

Stage 2.9.6 only reads the persisted evidence already introduced before Stage 2.9.6.

## Environment controls

Optional VulnDesk queue thresholds:

- `CTI_DIAGNOSTICS_QUEUE_WARN_THRESHOLD` (default `100`)
- `CTI_DIAGNOSTICS_QUEUE_FAIL_THRESHOLD` (default `1000`)

## Roadmap

- 2.9.1 Canonical Lineage Projection — complete
- 2.9.2 Task Lineage Probe API — complete
- 2.9.3 Mission Lineage Reconstruction — complete
- 2.9.4 Cross-Subsystem Governance Correlation — complete
- 2.9.5 Integrity / Violation Probe — complete
- **2.9.6 Health / Diagnostics — implemented**
- 2.9.7 GUI — optional
- 2.9.8 E2E Acceptance — next closure stage (GUI may be skipped)

# VulnDesk Stage 2.9.5 — Integrity / Violation Probe

## Baseline analyzed

- `Vulndesk(20260829-081222).zip`
- `Vulndesk(20260829-081215).sql`
- `aptsGSS(20260829-081215).zip`
- `AptsGSS(20260829-081214).sql`

The baseline already contains Stage 2.9.4 Cross-Subsystem Governance Correlation with
`control_version = hybrid-event-driven-2.15-cross-subsystem-governance-correlation`.

Stage 2.9.5 does **not** move Governance authority into VulnDesk. It adds a deterministic,
read-only classifier over:

1. canonical Task/Mission lineage from Stage 2.9.1/2.9.3; and
2. authoritative correlation facts attached by Stage 2.9.4.

No aptsGSS schema or application change is required for Stage 2.9.5 because the Stage 2.9.4
mission correlation snapshot already exposes the authoritative records required by this probe.

## New VulnDesk control version

`hybrid-event-driven-2.16-integrity-violation-probe`

## New integrity engine

`cti_services/integrity_probe.py`

Primary class:

`IntegrityViolationProbe`

Schema:

`cti-integrity-probe-v1`

The probe is read-only. It never:

- changes a TaskContract;
- repairs lineage;
- creates or changes a PolicyDecision;
- treats a local inference as Governance authority.

## Core Stage 2.9.5 invariants

### INV-295-01 — governed dispatch requires exact PolicyDecision binding

Violation code:

`DISPATCH_WITHOUT_POLICY_DECISION`

A TaskContract with `authorization_mode=REQUIRED` must not reach `TASK_DISPATCHED` without
an exact `policy_decision_id` on the TaskContract/governance binding and the dispatch event.

Severity: `CRITICAL`.

### INV-295-02 — revocation prevents later dispatch

Violation code:

`DISPATCH_AFTER_REVOCATION`

A `TASK_DISPATCHED` event occurring after `TASK_AUTHORIZATION_REVOKED` is a violation.

Severity: `CRITICAL`.

A correct sequence such as:

`TASK_AUTHORIZATION_REVOKED -> TASK_DISPATCH_BLOCKED`

with no later dispatch is explicitly classified as correct revocation enforcement and is **not**
a violation.

### INV-295-03 — TaskContract scope equals authoritative PolicyDecision scope

Violation code:

`TASK_SCOPE_POLICY_SCOPE_MISMATCH`

The local TaskContract `scope_contract_id` must equal the authoritative Governance
PolicyDecision `scope_contract_id` as proven by the Stage 2.9.4 field comparison.

Severity: `CRITICAL`.

### INV-295-04 — COMPLETED requires prior DISPATCHED

Violation code:

`COMPLETED_WITHOUT_DISPATCHED`

A canonical completed TaskContract must have a prior `TASK_DISPATCHED` event.

Severity: `HIGH`.

Historical/partial lineage projections are not falsely promoted to a violation merely because
an old event is absent. Such cases are marked `UNVERIFIABLE` when strict canonical event
history is not available.

## Stage 2.9.4 facts promoted to Stage 2.9.5 classifications

The probe also classifies authoritative provenance anomalies that Stage 2.9.4 deliberately
reported as correlation facts only:

- `GOVERNANCE_REQUIRED_REFERENCE_MISSING` — required request/decision/scope/event identity
  cannot be resolved against aptsGSS;
- `GOVERNANCE_FIELD_MISMATCH` — asserted local Governance binding differs from the
  authoritative record;
- `GOVERNANCE_EVENT_REFERENCE_MISSING` — mission CTI event points to a missing
  authoritative `gevent-*` record.

A Governance outage does **not** become a fabricated integrity violation. Clean local lineage
with unavailable authoritative correlation is returned as:

`status = UNVERIFIABLE`

with an explicit verification reason.

## Probe statuses

- `PASS` — no violations and all required evidence was verifiable;
- `VIOLATION_DETECTED` — at least one evidence-backed integrity violation exists;
- `UNVERIFIABLE` — no proven violation, but required authoritative/canonical evidence is
  unavailable or incomplete.

If both a local violation and an evidence-availability problem exist, the status remains
`VIOLATION_DETECTED` and `verification_complete=false` exposes the remaining uncertainty.

## New HTTP probe endpoints

- `GET /api/cti/tasks/{task_id}/integrity`
- `GET /api/cti/missions/{mission_id}/integrity`

The existing lineage endpoints remain available and are now enriched with an
`integrity_probe` section:

- `GET /api/cti/tasks/{task_id}/lineage`
- `GET /api/cti/missions/{mission_id}/lineage`

The dedicated probe endpoints return only the Stage 2.9.5 integrity report inside the normal
API envelope.

## Metadata updates

Task lineage gains:

- `integrity_probe`;
- `governance_binding.integrity_status`;
- `projection_metadata.integrity_classification_status`;
- `projection_metadata.integrity_violation_count`.

Mission lineage gains:

- `integrity_probe`;
- `projection_metadata.integrity_classification_status`;
- `projection_metadata.integrity_violation_count`;
- `projection_metadata.integrity_verification_complete`.

The Stage 2.9.4 `governance_correlation.integrity_classification_status` marker is updated to
the Stage 2.9.5 result after classification.

## Health / interface discovery

`GET /health` now reports:

`integrity_probe_mode = READ_ONLY_CANONICAL_LINEAGE_PLUS_AUTHORITATIVE_CORRELATION`

This is only a capability marker. Broad health/diagnostics aggregation remains Stage 2.9.6.

The interface catalog now advertises both integrity endpoints.

## Database migration

**NONE REQUIRED.**

The supplied schemas already persist all evidence required for Stage 2.9.5:

VulnDesk:

- `cti_task_contracts`;
- `cti_events`;
- `cti_decision_traces`;
- `cti_audit_log`.

aptsGSS authoritative correlation source:

- `gov_scope_contracts`;
- `gov_authorization_requests`;
- `gov_policy_decisions`;
- `gov_event_outbox`;
- `gov_audit_log`.

No cross-database foreign key is introduced.

## Files added

- `cti_services/integrity_probe.py`
- `tests/test_integrity_violation_probe_stage2_9_5.py`
- `STAGE2_9_5_ACCEPTANCE.ps1`
- `STAGE2_9_5_ACCEPTANCE.sql`
- `PATCH_NOTES_STAGE2_9_5_INTEGRITY_VIOLATION_PROBE.md`
- `BUILD_VALIDATION_STAGE2_9_5.txt`
- `INSTALL_STAGE2_9_5.txt`

## Files changed

- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/pentest_enrichment_api_service.py`
- `cti_services/interface_catalog.py`
- `cti_services/__init__.py`
- current-control assertions in Stage 2.9.1–2.9.4 regression tests.

## Roadmap position

- 2.9.1 Canonical Lineage Projection Model — complete
- 2.9.2 Task Lineage Probe API — complete
- 2.9.3 Mission Lineage Reconstruction — complete
- 2.9.4 Cross-Subsystem Governance Correlation — complete baseline
- **2.9.5 Integrity / Violation Probe — implemented**
- 2.9.6 Health / diagnostics — next after runtime acceptance of 2.9.5
- 2.9.7 GUI — optional
- 2.9.8 E2E Acceptance — final Stage 2.9 closure

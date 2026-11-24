# VulnDesk Stage 2.9.3 — Mission Lineage Reconstruction

## Baseline analyzed

- `Vulndesk(20260829-001656).zip`
- `Vulndesk(10).sql`
- `aptsGSS(20260829-001650).zip`
- `AptsGSS(10).sql`

The baseline already contains Stage 2.9.1 canonical Task projection and Stage 2.9.2
`GET /api/cti/tasks/{task_id}/lineage`. The database contains the complete local source
set needed for mission reconstruction: `cti_missions`, `cti_task_contracts`, `cti_events`,
`cti_decision_traces`, and `cti_audit_log`.

No schema migration is required. No aptsGSS code/schema change is required in Stage 2.9.3.
Cross-subsystem Governance correlation remains reserved for Stage 2.9.4.

## New control version

`hybrid-event-driven-2.14-mission-lineage-reconstruction`

## New canonical read operation

`CanonicalLineageProjector.project_mission(mission_id)`

The reconstruction is rooted at the persisted `cti_missions` row and composes every
canonical Stage 2.9.1 Task projection belonging to that mission. It additionally reads the
complete mission-wide event, decision-trace, and audit streams so causal relationships that
cross Task boundaries can be resolved at mission scope.

### Mission projection contract

- `projection_schema_version = cti-lineage-projection-v1`
- `projection_scope = MISSION`
- persisted mission snapshot with decoded JSON fields;
- `task_lineages[]` containing unchanged canonical TASK projections;
- mission-wide `events[]`;
- mission-wide `causal_edges[]`;
- deterministic `causal_order_event_ids[]` with known parents before children;
- `root_event_ids[]` for explicit events without a causal parent;
- mission-wide `decision_traces[]` and `audit_records[]`;
- reconstructed mission/task lifecycle summary;
- non-judgmental structural facts for unresolved parents, orphan task references,
  task-less mission events, and TaskContracts with no projected events.

## Structural-fact boundary

Stage 2.9.3 detects and preserves structural facts but **does not classify violations**.

`structural_facts.classification = STRUCTURAL_FACTS_ONLY_STAGE_2_9_3`

Examples:

- a `causation_event_id` whose parent is not present in the mission projection;
- an event whose `task_id` has no TaskContract in the same mission;
- a TaskContract with no direct or accepted historical-fallback events.

The projection explicitly reports:

- `governance_correlation_status = NOT_EVALUATED_STAGE_2_9_4`
- `integrity_classification_status = NOT_EVALUATED_STAGE_2_9_5`

Thus Stage 2.9.3 does not query aptsGSS, does not invent authority, and does not label a
missing parent/orphan as an integrity violation.

## New HTTP interface

`GET /api/cti/missions/{mission_id}/lineage`

Success envelope:

```json
{
  "status": "completed",
  "mission_id": "mission-...",
  "lineage": {
    "projection_schema_version": "cti-lineage-projection-v1",
    "projection_scope": "MISSION"
  }
}
```

### Error contract

- `400 INVALID_MISSION_ID` — blank mission identity.
- `404 MISSION_LINEAGE_NOT_FOUND` — no canonical `cti_missions` root.
- `503 LINEAGE_SCHEMA_UNAVAILABLE` — required persisted lineage schema is unavailable.

The existing `GET /api/cti/missions/{mission_id}` mission-status route remains unchanged.
The new `/lineage` route is matched first to avoid path ambiguity.

## Causal ordering

Stage 2.9.3 performs a deterministic stable topological ordering over known intra-mission
`causation_event_id` edges. Persisted order is used as the stable tie-breaker. Unknown
parents are not synthesized. If the known graph cannot be fully resolved, remaining events
are preserved in persisted order and `causal_order_fully_resolved=false` is reported as a
structural fact. Integrity/cycle classification remains Stage 2.9.5.

## Files changed

- `cti_services/lineage_projection.py`
- `cti_services/__init__.py`
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/pentest_enrichment_api_service.py`
- `cti_services/interface_catalog.py`
- `tests/test_canonical_lineage_projection_stage2_9_1.py` — current control-version regression
- `tests/test_task_lineage_probe_stage2_9_2.py` — current control-version regression

## Files added

- `tests/test_mission_lineage_reconstruction_stage2_9_3.py`
- `STAGE2_9_3_ACCEPTANCE.ps1`
- `STAGE2_9_3_ACCEPTANCE.sql`
- `PATCH_NOTES_STAGE2_9_3_MISSION_LINEAGE_RECONSTRUCTION.md`
- `BUILD_VALIDATION_STAGE2_9_3.txt`
- `INSTALL_STAGE2_9_3.txt`

## Stage boundary after this patch

2.9.1 Canonical Lineage Projection Model — complete foundation  
2.9.2 Task Lineage Probe API — preserved  
**2.9.3 Mission Lineage Reconstruction — implemented**  
2.9.4 Cross-Subsystem Governance Correlation — next  
2.9.5 Integrity / Violation Probe — not implemented here

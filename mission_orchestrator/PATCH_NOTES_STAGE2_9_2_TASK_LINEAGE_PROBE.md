# VulnDesk Stage 2.9.2 — Task Lineage Probe API

## Baseline

Stage 2.9.1 already provides the deterministic `CanonicalLineageProjector` and the
`CtiSubsystemOrchestrator.project_task_lineage(task_id)` service boundary. Stage 2.9.2
exposes that exact projection to operators/integration clients without duplicating SQL or
lineage reconstruction logic in the HTTP transport layer.

No database migration is required. No aptsGSS source/schema change is required.

## New control version

`hybrid-event-driven-2.13-task-lineage-probe`

## New HTTP interface

`GET /api/cti/tasks/{task_id}/lineage`

Success response:

```json
{
  "status": "completed",
  "task_id": "task-...",
  "lineage": {
    "projection_schema_version": "cti-lineage-projection-v1",
    "projection_scope": "TASK"
  }
}
```

The `lineage` member is returned directly from the canonical Stage 2.9.1 projector.
The HTTP adapter does not query lineage tables itself and does not repair, classify, or
reinterpret persisted lineage.

## Error contract

- `400 INVALID_TASK_ID` — blank task identity.
- `404 TASK_LINEAGE_NOT_FOUND` — no corresponding `cti_task_contracts` root.
- `503 LINEAGE_SCHEMA_UNAVAILABLE` — required Stage 2.8 lineage schema is unavailable;
  the probe fails closed.
- unexpected failures continue through the existing generic API error boundary.

Expected domain errors do not include Python traceback payloads.

## Authority and stage boundaries

Stage 2.9.2 is strictly read-only.

- It does not create or change PolicyDecision authority.
- It does not mutate TaskContract state.
- It does not emit lifecycle events.
- It does not perform cross-subsystem Governance correlation; projected Governance refs
  remain `correlation_status=NOT_EVALUATED_STAGE_2_9_4`.
- It does not classify missing causal parents or other structural facts as violations;
  integrity classification remains Stage 2.9.5.

## Interface catalog

The CTI Component Manager interface catalog now advertises:

`GET /api/cti/tasks/{task_id}/lineage`

under the operator/diagnostic provided interfaces for CTI-INF01.

## Files changed

- `cti_services/pentest_enrichment_api_service.py`
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/interface_catalog.py`
- `tests/test_canonical_lineage_projection_stage2_9_1.py` — regression expectation moved to current control version
- `tests/test_task_lineage_probe_stage2_9_2.py` — new
- `STAGE2_9_2_ACCEPTANCE.ps1` — new runtime HTTP acceptance
- `STAGE2_9_2_ACCEPTANCE.sql` — new persistence cross-check
- `BUILD_VALIDATION_STAGE2_9_2.txt` — new

## Runtime acceptance

Use a fresh TaskContract created by the patched runtime:

```powershell
.\STAGE2_9_2_ACCEPTANCE.ps1 -TaskId "<fresh-task-id>"
```

Then set the same TaskId in `STAGE2_9_2_ACCEPTANCE.sql` and compare persisted event,
causal, decision, and audit rows with the HTTP projection.

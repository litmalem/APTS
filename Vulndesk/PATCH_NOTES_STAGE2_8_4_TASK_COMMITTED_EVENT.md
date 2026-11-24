# VulnDesk Stage 2.8.4 — TASK_COMMITTED Event

## Scope

Stage 2.8.4 turns a successful TaskContract commit into an explicit CTI lineage event.
It does **not** change authorization semantics, pre-dispatch revalidation, granular
revocation, or aptsGSS PolicyDecision ownership.

## Runtime version

`hybrid-event-driven-2.7-task-committed-lineage`

## Implemented behavior

After `TaskContract.validate()` succeeds and persistence of the TaskContract is attempted,
CTI-A01 emits one `TASK_COMMITTED` event with:

- `event_schema_version = cti-event-v2`
- `trace_id = TaskContract.trace_id`
- `proposal_id`
- `task_id`
- `policy_decision_id` (only when authorization mode is REQUIRED)
- `authorization_request_id` (only when authorization mode is REQUIRED)
- task/component/type/plan metadata in payload
- authorization mode
- scope contract/version and policy metadata as references only

The full authoritative PolicyDecision is **not** copied into the event. aptsGSS remains the
PolicyDecision authority; the complete bound snapshot stays in `cti_task_contracts`.

Internal tasks emit `authorization_mode=NOT_REQUIRED_INTERNAL` and do not manufacture
external authority.

## Compatibility

Migration 07 remains the only database migration required for Stage 2.8.1-2.8.4.
If Migration 07 has already been applied, **do not create another schema migration** for
2.8.4. Restart VulnDesk after replacing the source.

## Files changed

- `cti_services/event_bus.py` (Stage 2.8 v2 envelope foundation included)
- `cti_services/contracts.py` (stable non-empty TaskContract trace invariant)
- `cti_services/cti_subsystem_orchestrator.py` (`TASK_COMMITTED` emission)

## Files added

- `sql_update_cti_harmonized/07_task_lineage_event_traceability.sql`
- `tests/test_task_lineage_event_v2_stage2_8.py`
- `tests/test_task_committed_event_stage2_8_4.py`
- `STAGE2_8_4_ACCEPTANCE.sql`
- `BUILD_VALIDATION_STAGE2_8_4.txt`

## Recommended local test sequence

```powershell
python -m pytest -q .\tests\test_task_committed_event_stage2_8_4.py

python -m pytest -q `
    .\tests\test_task_lineage_event_v2_stage2_8.py `
    .\tests\test_task_committed_event_stage2_8_4.py `
    .\tests\test_cti_event_driven_runtime.py `
    .\tests\test_policydecision_taskcontract_stage2.py `
    .\tests\test_pre_dispatch_revalidation_stage2_6.py `
    .\tests\test_granular_revocation_stage2_7.py

python -m pytest -q --ignore=tests/test_nvd_bulk_upsert.py
python -m pytest -q
```

Then run `STAGE2_8_4_ACCEPTANCE.sql` against the VulnDesk database after executing at
least one mission that commits an internal task.

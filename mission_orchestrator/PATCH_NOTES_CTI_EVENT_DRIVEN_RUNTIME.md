# VulnDesk CTI Event-Driven Runtime Patch

Baseline: `vulndesk(6).zip`
Architecture target: Actionable-Adaptive CTI Subsystem, CTI-A01 Hybrid Reactive-Deliberative, CTI-A02 RAO.

## What changed

1. **CTI-A02 is connected to VulnDesk source sync** through `cti_services/source_sync_connector.py`.
   - `nvd-cve` -> `SyncService.run_incremental_sync()`
   - `nvd-cpe` -> bounded `CpeDictionarySyncService` refresh
   - `mitre-attack` -> `MitreAttackSyncService.run_incremental_sync()`
   - Source selection stays in CTI-A02; the connector is non-agent infrastructure and executes only after an ALLOW source-acquisition policy decision.

2. **Typed Event Bus + Event Dispatcher** were added.
   - `cti_services/event_bus.py`
   - `cti_services/event_dispatcher.py`
   - Events remain persisted in `cti_events`.
   - Optional delivery telemetry is stored in `cti_event_deliveries` after migration 02.

3. **CTI-A01 was refactored from a procedural pipeline into event-driven Hybrid Reactive-Deliberative orchestration**.
   - `MISSION_STARTED -> CTI_ACQUISITION_EVALUATE -> PIPELINE_ADVANCE -> TASK_*`
   - Versioned DAG still defines dependencies.
   - Deliberative proposals are produced only for ready tasks.
   - Reactive proposals use deterministic precedence:
     `SAFETY_POLICY > CRITICAL_FAILURE > FRESHNESS_EMERGENCY > MISSION_PRIORITY > RECOVERY > DELIBERATIVE_OPTIMIZATION`.
   - Stale proposals are invalidated and trigger a new plan version.
   - `TASK_FAILED` is now a real reactive condition (`RETRY_OR_REPLAN`).

4. **External trigger APIs** were added to the shared API runtime.
   - `POST /api/cti/missions/start`
   - `GET /api/cti/missions/{mission_id}`
   - `POST /api/cti/events/publish`
   - `GET /api/cti/events/{mission_id}?limit=100`
   - Existing blocking `/api/cti/enrich-scan` remains compatible but now waits for the event-driven mission runtime.

5. **Infrastructure component registry** now includes:
   - CTI-INF02 — CTI Event Bus
   - CTI-INF03 — CTI Event Dispatcher
   - CTI-INF04 — CTI Source Sync Connector

## Migration

Run after the existing harmonized migration:

`sql_update_cti_harmonized/02_cti_event_driven_runtime_migration.sql`

This migration is non-destructive. It adds `cti_event_deliveries`, registers CTI-INF02/03/04 and adds bounded sync profiles to the three CTI sources.

## Default acquisition behavior

`/api/cti/enrich-scan` now defaults to `auto_acquire_cti=true`, but source refresh is bounded to one selected source action per mission unless the payload changes it.

Useful request fields:

- `auto_acquire_cti`: true/false
- `cti_acquisition_max_actions`: default 1
- `cti_source_set`: e.g. `["nvd-cve", "mitre-attack"]`
- `cti_source_priority_overrides`: per-source mission relevance
- `allow_degraded_acquisition`: default true
- `cti_task_max_retries`: default 1
- `cti_runtime_timeout_seconds`: default 600

For deterministic local-only testing, send `"auto_acquire_cti": false`.

## Validation performed

- `python -m compileall -q .` : PASS
- `python -m unittest discover -s tests -p 'test_*.py' -v` : **11/11 PASS**
- New regression tests cover typed event dispatch, event-driven DAG completion, CTI-A02 -> source sync trigger, reactive pre-emption, and TASK_FAILED recovery mapping.

## Architectural boundaries retained

- CTI source acquisition is read-only intelligence acquisition, not target actuation.
- Attack-path reasoning remains non-executable.
- Risk prioritization remains recommendation-only.
- PIP remains a Data Artifact and not an execution command.

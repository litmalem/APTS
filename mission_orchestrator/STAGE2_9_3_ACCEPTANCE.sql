/*
  VulnDesk Stage 2.9.3 — Mission Lineage Reconstruction

  No database migration is required. This script cross-checks the persisted
  sources used by:

      GET /api/cti/missions/{mission_id}/lineage

  Run STAGE2_9_3_ACCEPTANCE.ps1 first and use the same MissionId below.
*/

SET @stage293_mission_id = 'REPLACE_WITH_FRESH_MISSION_ID';

/* A. Canonical mission root. Expected: exactly one row. */
SELECT mission_id,
       status,
       state_version,
       plan_version,
       policy_version,
       pip_readiness,
       latest_pip_id,
       started_at,
       finished_at,
       created_at,
       updated_at
FROM cti_missions
WHERE mission_id = @stage293_mission_id;

/* B. All TaskContracts composed into lineage.task_lineages[]. */
SELECT id,
       task_id,
       mission_id,
       trace_id,
       assigned_component,
       task_type,
       status,
       authorization_mode,
       policy_decision_id,
       authorization_request_id,
       pre_dispatch_revalidation_id,
       revocation_id,
       revocation_status,
       created_at,
       updated_at
FROM cti_task_contracts
WHERE mission_id = @stage293_mission_id
ORDER BY id ASC;

/* C. Mission-wide event stream represented by lineage.events[]. */
SELECT id,
       event_id,
       event_schema_version,
       mission_id,
       trace_id,
       proposal_id,
       task_id,
       event_type,
       causation_event_id,
       upstream_event_id,
       policy_decision_id,
       authorization_request_id,
       revalidation_id,
       created_at
FROM cti_events
WHERE mission_id = @stage293_mission_id
ORDER BY id ASC;

/* D. Mission-wide causal edges. cause_in_projection must be 1 when the parent
      exists inside the same mission reconstruction. */
SELECT child.id,
       child.causation_event_id AS cause_event_id,
       child.event_id AS effect_event_id,
       CASE WHEN parent.event_id IS NULL THEN 0 ELSE 1 END AS cause_in_projection
FROM cti_events child
LEFT JOIN cti_events parent
  ON parent.mission_id = child.mission_id
 AND parent.event_id = child.causation_event_id
WHERE child.mission_id = @stage293_mission_id
  AND child.causation_event_id IS NOT NULL
ORDER BY child.id ASC;

/* E. Explicit causal roots represented by lineage.root_event_ids[]. */
SELECT id, event_id, event_type, task_id, trace_id, created_at
FROM cti_events
WHERE mission_id = @stage293_mission_id
  AND causation_event_id IS NULL
ORDER BY id ASC;

/* F. Unresolved causal references represented as structural facts only.
      Stage 2.9.3 does NOT classify these as integrity violations. */
SELECT child.id,
       child.event_id AS effect_event_id,
       child.causation_event_id
FROM cti_events child
LEFT JOIN cti_events parent
  ON parent.mission_id = child.mission_id
 AND parent.event_id = child.causation_event_id
WHERE child.mission_id = @stage293_mission_id
  AND child.causation_event_id IS NOT NULL
  AND parent.event_id IS NULL
ORDER BY child.id ASC;

/* G. Events carrying a task_id for which no TaskContract exists in the mission.
      These become structural_facts.orphan_task_event_ids only. */
SELECT e.id, e.event_id, e.task_id, e.event_type, e.created_at
FROM cti_events e
LEFT JOIN cti_task_contracts t
  ON t.mission_id = e.mission_id
 AND t.task_id = e.task_id
WHERE e.mission_id = @stage293_mission_id
  AND e.task_id IS NOT NULL
  AND e.task_id <> ''
  AND t.task_id IS NULL
ORDER BY e.id ASC;

/* H. TaskContracts without either direct task events or the explicit historical
      trace fallback admitted by the Stage 2.9.1 projector. */
SELECT t.task_id, t.trace_id, t.status
FROM cti_task_contracts t
WHERE t.mission_id = @stage293_mission_id
  AND NOT EXISTS (
      SELECT 1
      FROM cti_events e
      WHERE e.task_id = t.task_id
         OR (
              e.mission_id = t.mission_id
          AND e.trace_id = t.trace_id
          AND (e.task_id IS NULL OR e.task_id = '')
         )
  )
ORDER BY t.id ASC;

/* I. Mission-wide decision stream. */
SELECT id,
       trace_id,
       lineage_trace_id,
       mission_id,
       proposal_id,
       task_id,
       decision_type,
       policy_decision_id,
       authorization_request_id,
       revalidation_id,
       upstream_event_id,
       created_at
FROM cti_decision_traces
WHERE mission_id = @stage293_mission_id
ORDER BY id ASC;

/* J. Mission-wide audit stream. */
SELECT id,
       audit_id,
       trace_id,
       event_type,
       upstream_event_ref,
       downstream_event_ref,
       created_at
FROM cti_audit_log
WHERE mission_id = @stage293_mission_id
ORDER BY id ASC;

/* K. Summary counts: compare with lineage.projection_metadata. */
SELECT @stage293_mission_id AS mission_id,
       (SELECT COUNT(*) FROM cti_task_contracts WHERE mission_id=@stage293_mission_id) AS task_count,
       (SELECT COUNT(*) FROM cti_events WHERE mission_id=@stage293_mission_id) AS event_count,
       (SELECT COUNT(*) FROM cti_events WHERE mission_id=@stage293_mission_id AND causation_event_id IS NOT NULL) AS causal_edge_count,
       (SELECT COUNT(*) FROM cti_events WHERE mission_id=@stage293_mission_id AND causation_event_id IS NULL) AS root_event_count,
       (SELECT COUNT(*) FROM cti_decision_traces WHERE mission_id=@stage293_mission_id) AS decision_trace_count,
       (SELECT COUNT(*) FROM cti_audit_log WHERE mission_id=@stage293_mission_id) AS audit_record_count;

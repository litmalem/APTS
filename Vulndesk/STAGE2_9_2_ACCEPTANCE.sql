/*
  VulnDesk Stage 2.9.2 — Task Lineage Probe API

  No database migration is required for Stage 2.9.2. This SQL verifies the
  persisted canonical projection sources for the same TaskContract queried via:

      GET /api/cti/tasks/{task_id}/lineage

  First run STAGE2_9_2_ACCEPTANCE.ps1 against the HTTP API, then use the same
  TaskId below to compare the API projection with persisted source rows.
*/

SET @stage292_task_id = 'REPLACE_WITH_FRESH_TASK_ID';

/* A. Canonical TaskContract root. Expected: exactly one row. */
SELECT task_id,
       mission_id,
       trace_id,
       assigned_component,
       task_type,
       status,
       authorization_mode,
       authorization_authority,
       authorization_authority_component,
       authorization_governance_event_id,
       policy_decision_id,
       authorization_request_id,
       pre_dispatch_revalidation_id,
       pre_dispatch_governance_event_id,
       revocation_id,
       revocation_event_id,
       revocation_status,
       created_at,
       updated_at
FROM cti_task_contracts
WHERE task_id = @stage292_task_id;

SET @stage292_mission_id = (
    SELECT mission_id
    FROM cti_task_contracts
    WHERE task_id = @stage292_task_id
    LIMIT 1
);

SET @stage292_trace_id = (
    SELECT trace_id
    FROM cti_task_contracts
    WHERE task_id = @stage292_task_id
    LIMIT 1
);

/* B. Events represented by lineage.events[] in persisted order. */
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
WHERE task_id = @stage292_task_id
   OR (
        mission_id = @stage292_mission_id
    AND trace_id = @stage292_trace_id
    AND (task_id IS NULL OR task_id = '')
   )
ORDER BY id ASC;

/* C. Structural causal edges represented by lineage.causal_edges[]. */
SELECT child.event_id AS effect_event_id,
       child.causation_event_id AS cause_event_id,
       CASE WHEN parent.event_id IS NULL THEN 0 ELSE 1 END AS cause_in_projection
FROM cti_events child
LEFT JOIN cti_events parent
  ON parent.event_id = child.causation_event_id
 AND (
       parent.task_id = @stage292_task_id
       OR (
            parent.mission_id = @stage292_mission_id
        AND parent.trace_id = @stage292_trace_id
        AND (parent.task_id IS NULL OR parent.task_id = '')
       )
    )
WHERE (
       child.task_id = @stage292_task_id
       OR (
            child.mission_id = @stage292_mission_id
        AND child.trace_id = @stage292_trace_id
        AND (child.task_id IS NULL OR child.task_id = '')
       )
      )
  AND child.causation_event_id IS NOT NULL
ORDER BY child.id ASC;

/* D. Decision traces represented by lineage.decision_traces[]. */
SELECT id,
       trace_id AS decision_trace_id,
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
WHERE task_id = @stage292_task_id
   OR (
        mission_id = @stage292_mission_id
    AND lineage_trace_id = @stage292_trace_id
    AND (task_id IS NULL OR task_id = '')
   )
ORDER BY id ASC;

/* E. Audit bridge rows represented by lineage.audit_records[]. */
SELECT a.id,
       a.audit_id,
       a.trace_id AS decision_trace_id,
       a.event_type,
       a.upstream_event_ref,
       a.downstream_event_ref,
       a.created_at
FROM cti_audit_log a
WHERE a.mission_id = @stage292_mission_id
  AND (
       a.trace_id IN (
           SELECT d.trace_id
           FROM cti_decision_traces d
           WHERE d.task_id = @stage292_task_id
              OR (
                   d.mission_id = @stage292_mission_id
               AND d.lineage_trace_id = @stage292_trace_id
               AND (d.task_id IS NULL OR d.task_id = '')
              )
       )
       OR a.downstream_event_ref IN (
           SELECT e.event_id
           FROM cti_events e
           WHERE e.task_id = @stage292_task_id
              OR (
                   e.mission_id = @stage292_mission_id
               AND e.trace_id = @stage292_trace_id
               AND (e.task_id IS NULL OR e.task_id = '')
              )
       )
  )
ORDER BY a.id ASC;

/* F. Counts should match lineage.projection_metadata.*_count. */
SELECT @stage292_task_id AS task_id,
       @stage292_mission_id AS mission_id,
       @stage292_trace_id AS trace_id,
       (SELECT COUNT(*)
          FROM cti_events e
         WHERE e.task_id = @stage292_task_id
            OR (e.mission_id=@stage292_mission_id AND e.trace_id=@stage292_trace_id AND (e.task_id IS NULL OR e.task_id=''))) AS event_count,
       (SELECT COUNT(*)
          FROM cti_decision_traces d
         WHERE d.task_id = @stage292_task_id
            OR (d.mission_id=@stage292_mission_id AND d.lineage_trace_id=@stage292_trace_id AND (d.task_id IS NULL OR d.task_id=''))) AS decision_trace_count;

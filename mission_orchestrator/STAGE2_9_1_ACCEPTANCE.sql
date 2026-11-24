/*
  VulnDesk Stage 2.9.1 — Canonical Lineage Projection Model

  No migration is required. This script validates that the persisted Stage 2.8
  lineage sources needed by cti-lineage-projection-v1 are present and can be
  deterministically read for one TaskContract.

  Replace the task below with a fresh task_id produced after installing the patch.
*/

SET @stage291_task_id = 'REPLACE_WITH_FRESH_TASK_ID';

/* A. Required Stage 2.9.1 source tables. Expected: 4 rows, all PRESENT. */
SELECT required.table_name,
       CASE WHEN actual.table_name IS NULL THEN 'MISSING' ELSE 'PRESENT' END AS status
FROM (
    SELECT 'cti_task_contracts' AS table_name
    UNION ALL SELECT 'cti_events'
    UNION ALL SELECT 'cti_decision_traces'
    UNION ALL SELECT 'cti_audit_log'
) required
LEFT JOIN information_schema.tables actual
  ON actual.table_schema = DATABASE()
 AND actual.table_name = required.table_name
ORDER BY required.table_name;

/* B. Required first-class columns. Expected: missing_count = 0. */
SELECT COUNT(*) AS missing_count
FROM (
    SELECT 'cti_task_contracts' table_name, 'task_id' column_name UNION ALL
    SELECT 'cti_task_contracts', 'mission_id' UNION ALL
    SELECT 'cti_task_contracts', 'trace_id' UNION ALL
    SELECT 'cti_task_contracts', 'policy_decision_id' UNION ALL
    SELECT 'cti_task_contracts', 'authorization_request_id' UNION ALL
    SELECT 'cti_task_contracts', 'authorization_governance_event_id' UNION ALL
    SELECT 'cti_task_contracts', 'pre_dispatch_governance_event_id' UNION ALL
    SELECT 'cti_events', 'event_id' UNION ALL
    SELECT 'cti_events', 'mission_id' UNION ALL
    SELECT 'cti_events', 'trace_id' UNION ALL
    SELECT 'cti_events', 'causation_event_id' UNION ALL
    SELECT 'cti_events', 'upstream_event_id' UNION ALL
    SELECT 'cti_events', 'proposal_id' UNION ALL
    SELECT 'cti_events', 'task_id' UNION ALL
    SELECT 'cti_events', 'policy_decision_id' UNION ALL
    SELECT 'cti_events', 'authorization_request_id' UNION ALL
    SELECT 'cti_events', 'revalidation_id' UNION ALL
    SELECT 'cti_decision_traces', 'trace_id' UNION ALL
    SELECT 'cti_decision_traces', 'lineage_trace_id' UNION ALL
    SELECT 'cti_decision_traces', 'mission_id' UNION ALL
    SELECT 'cti_decision_traces', 'task_id' UNION ALL
    SELECT 'cti_decision_traces', 'upstream_event_id' UNION ALL
    SELECT 'cti_audit_log', 'trace_id' UNION ALL
    SELECT 'cti_audit_log', 'mission_id' UNION ALL
    SELECT 'cti_audit_log', 'upstream_event_ref' UNION ALL
    SELECT 'cti_audit_log', 'downstream_event_ref'
) required
LEFT JOIN information_schema.columns actual
  ON actual.table_schema = DATABASE()
 AND actual.table_name = required.table_name
 AND actual.column_name = required.column_name
WHERE actual.column_name IS NULL;

/* C. Canonical TaskContract root. Expected: exactly one row. */
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
WHERE task_id = @stage291_task_id;

SET @stage291_mission_id = (
    SELECT mission_id
    FROM cti_task_contracts
    WHERE task_id = @stage291_task_id
    LIMIT 1
);

SET @stage291_trace_id = (
    SELECT trace_id
    FROM cti_task_contracts
    WHERE task_id = @stage291_task_id
    LIMIT 1
);

/* D. Event projection source, in persisted order. */
SELECT id,
       event_id,
       event_schema_version,
       mission_id,
       trace_id,
       proposal_id,
       task_id,
       event_type,
       source_component,
       severity,
       causation_event_id,
       upstream_event_id,
       policy_decision_id,
       authorization_request_id,
       revalidation_id,
       state_version,
       plan_version,
       policy_version,
       created_at
FROM cti_events
WHERE task_id = @stage291_task_id
   OR (
        mission_id = @stage291_mission_id
    AND trace_id = @stage291_trace_id
    AND (task_id IS NULL OR task_id = '')
   )
ORDER BY id ASC;

/* E. Structural causal edges. This does not classify violations (Stage 2.9.5). */
SELECT child.event_id AS effect_event_id,
       child.causation_event_id AS cause_event_id,
       CASE WHEN parent.event_id IS NULL THEN 0 ELSE 1 END AS cause_in_task_projection
FROM cti_events child
LEFT JOIN cti_events parent
  ON parent.event_id = child.causation_event_id
 AND (
       parent.task_id = @stage291_task_id
       OR (
            parent.mission_id = @stage291_mission_id
        AND parent.trace_id = @stage291_trace_id
        AND (parent.task_id IS NULL OR parent.task_id = '')
       )
    )
WHERE (
       child.task_id = @stage291_task_id
       OR (
            child.mission_id = @stage291_mission_id
        AND child.trace_id = @stage291_trace_id
        AND (child.task_id IS NULL OR child.task_id = '')
       )
      )
  AND child.causation_event_id IS NOT NULL
ORDER BY child.id ASC;

/* F. Decision projection source. */
SELECT id,
       trace_id AS decision_trace_id,
       lineage_trace_id,
       mission_id,
       proposal_id,
       task_id,
       decision_type,
       component_id,
       policy_decision_id,
       authorization_request_id,
       revalidation_id,
       upstream_event_id,
       created_at
FROM cti_decision_traces
WHERE task_id = @stage291_task_id
   OR (
        mission_id = @stage291_mission_id
    AND lineage_trace_id = @stage291_trace_id
    AND (task_id IS NULL OR task_id = '')
   )
ORDER BY id ASC;

/* G. Audit bridge rows selected by decision trace or downstream task event. */
SELECT a.id,
       a.audit_id,
       a.trace_id AS decision_trace_id,
       a.event_type,
       a.component_id,
       a.upstream_event_ref,
       a.downstream_event_ref,
       a.created_at
FROM cti_audit_log a
WHERE a.mission_id = @stage291_mission_id
  AND (
       a.trace_id IN (
           SELECT d.trace_id
           FROM cti_decision_traces d
           WHERE d.task_id = @stage291_task_id
              OR (
                   d.mission_id = @stage291_mission_id
               AND d.lineage_trace_id = @stage291_trace_id
               AND (d.task_id IS NULL OR d.task_id = '')
              )
       )
       OR a.downstream_event_ref IN (
           SELECT e.event_id
           FROM cti_events e
           WHERE e.task_id = @stage291_task_id
              OR (
                   e.mission_id = @stage291_mission_id
               AND e.trace_id = @stage291_trace_id
               AND (e.task_id IS NULL OR e.task_id = '')
              )
       )
  )
ORDER BY a.id ASC;

/* H. Summary expected by cti-lineage-projection-v1. */
SELECT @stage291_task_id AS task_id,
       @stage291_mission_id AS mission_id,
       @stage291_trace_id AS trace_id,
       (SELECT COUNT(*) FROM cti_events e
         WHERE e.task_id = @stage291_task_id
            OR (e.mission_id=@stage291_mission_id AND e.trace_id=@stage291_trace_id AND (e.task_id IS NULL OR e.task_id=''))) AS event_count,
       (SELECT COUNT(*) FROM cti_decision_traces d
         WHERE d.task_id = @stage291_task_id
            OR (d.mission_id=@stage291_mission_id AND d.lineage_trace_id=@stage291_trace_id AND (d.task_id IS NULL OR d.task_id=''))) AS decision_trace_count,
       (SELECT COUNT(DISTINCT e.upstream_event_id) FROM cti_events e
         WHERE (e.task_id = @stage291_task_id
            OR (e.mission_id=@stage291_mission_id AND e.trace_id=@stage291_trace_id AND (e.task_id IS NULL OR e.task_id='')))
           AND e.upstream_event_id IS NOT NULL) AS external_upstream_event_count;

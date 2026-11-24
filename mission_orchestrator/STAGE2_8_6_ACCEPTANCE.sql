-- Stage 2.8.6 acceptance probes -- Causal Event Chain
-- Migration 07 is sufficient; no new DB migration is required.
USE `vulndesk`;

-- Replace with fresh mission IDs created after deploying Stage 2.8.6.
SET @stage286_mission_id = 'REPLACE-WITH-STAGE286-MISSION-ID';
SET @stage286_revocation_mission_id = 'REPLACE-WITH-STAGE286-REVOCATION-MISSION-ID';

-- A. Positive evidence: task events and their direct local parent.
SELECT
    e.id,
    e.event_id,
    e.event_type,
    e.trace_id,
    e.task_id,
    e.causation_event_id,
    p.event_type AS parent_event_type,
    e.upstream_event_id,
    e.created_at
FROM cti_events e
LEFT JOIN cti_events p
       ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_mission_id
  AND e.event_type IN (
      'TASK_COMMITTED',
      'TASK_AUTHORIZATION_REVALIDATED',
      'TASK_DISPATCHED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_COMPLETED',
      'TASK_FAILED',
      'SOURCE_SYNC_PROGRESS',
      'SOURCE_SYNC_COMPLETED',
      'SOURCE_SYNC_DEGRADED',
      'SOURCE_SYNC_FAILED'
  )
ORDER BY e.id;

-- B. Internal-task causal invariant. Expected: 0 rows.
-- TASK_DISPATCHED must be caused by TASK_COMMITTED; TASK_COMPLETED/FAILED by TASK_DISPATCHED.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    e.causation_event_id,
    p.event_type AS parent_event_type
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
LEFT JOIN cti_events p ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_mission_id
  AND t.authorization_mode = 'NOT_REQUIRED_INTERNAL'
  AND (
      (e.event_type = 'TASK_DISPATCHED' AND (e.causation_event_id IS NULL OR p.event_type <> 'TASK_COMMITTED'))
      OR
      (e.event_type IN ('TASK_COMPLETED','TASK_FAILED') AND (e.causation_event_id IS NULL OR p.event_type <> 'TASK_DISPATCHED'))
  );

-- C. Governed task causal invariant. Expected: 0 rows for a successful REQUIRED task.
-- Revalidation is caused by commit; dispatch is caused by revalidation.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    e.causation_event_id,
    p.event_type AS parent_event_type,
    e.policy_decision_id,
    e.revalidation_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
LEFT JOIN cti_events p ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_mission_id
  AND t.authorization_mode = 'REQUIRED'
  AND (
      (e.event_type = 'TASK_AUTHORIZATION_REVALIDATED' AND
          (e.causation_event_id IS NULL OR p.event_type <> 'TASK_COMMITTED'))
      OR
      (e.event_type = 'TASK_DISPATCHED' AND
          (e.causation_event_id IS NULL OR p.event_type <> 'TASK_AUTHORIZATION_REVALIDATED'))
  );

-- D. Causal parent must stay inside the same mission/task when the parent is task-bound.
-- Expected: 0 rows.
SELECT
    e.event_id,
    e.event_type,
    e.mission_id,
    e.task_id,
    e.causation_event_id,
    p.mission_id AS parent_mission_id,
    p.task_id AS parent_task_id,
    p.event_type AS parent_event_type
FROM cti_events e
JOIN cti_events p ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_mission_id
  AND e.task_id IS NOT NULL
  AND p.task_id IS NOT NULL
  AND (e.mission_id <> p.mission_id OR e.task_id <> p.task_id);

-- E. Positive cross-subsystem revocation evidence.
-- Expected chain:
--   AUTHORIZATION_REVOKED(local ingress, upstream=gevent-*)
--      -> TASK_AUTHORIZATION_REVOKED
--      -> TASK_DISPATCH_BLOCKED or TASK_REVOCATION_STOP_REQUESTED
SELECT
    e.id,
    e.event_id,
    e.event_type,
    e.task_id,
    e.policy_decision_id,
    e.causation_event_id,
    p.event_type AS parent_event_type,
    e.upstream_event_id,
    e.created_at
FROM cti_events e
LEFT JOIN cti_events p ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_revocation_mission_id
  AND e.event_type IN (
      'AUTHORIZATION_REVOKED',
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_REVOCATION_STOP_REQUESTED'
  )
ORDER BY e.id;

-- F. Governance ingress must preserve gevent-* as upstream_event_id. Expected: 0 rows.
SELECT
    event_id,
    event_type,
    mission_id,
    upstream_event_id,
    payload_json
FROM cti_events
WHERE mission_id = @stage286_revocation_mission_id
  AND event_type = 'AUTHORIZATION_REVOKED'
  AND (
      upstream_event_id IS NULL
      OR TRIM(upstream_event_id) = ''
      OR upstream_event_id NOT LIKE 'gevent-%'
  );

-- G. Revocation causal-chain invariant. Expected: 0 rows.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    e.causation_event_id,
    p.event_type AS parent_event_type,
    e.upstream_event_id
FROM cti_events e
LEFT JOIN cti_events p ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage286_revocation_mission_id
  AND (
      (e.event_type = 'TASK_AUTHORIZATION_REVOKED' AND
          (e.causation_event_id IS NULL OR p.event_type <> 'AUTHORIZATION_REVOKED'))
      OR
      (e.event_type IN ('TASK_DISPATCH_BLOCKED','TASK_REVOCATION_STOP_REQUESTED') AND
          JSON_UNQUOTE(JSON_EXTRACT(e.payload_json, '$.revocation_id')) IS NOT NULL AND
          (e.causation_event_id IS NULL OR p.event_type <> 'TASK_AUTHORIZATION_REVOKED'))
  );

-- H. Child revocation events preserve the same upstream governance identity. Expected: 0 rows.
SELECT
    child.event_id,
    child.event_type,
    child.upstream_event_id,
    ingress.event_id AS ingress_event_id,
    ingress.upstream_event_id AS ingress_upstream_event_id
FROM cti_events child
JOIN cti_events ingress
  ON ingress.mission_id = child.mission_id
 AND ingress.event_type = 'AUTHORIZATION_REVOKED'
 AND ingress.event_id = (
     SELECT p.event_id
     FROM cti_events p
     WHERE p.event_id = CASE
         WHEN child.event_type = 'TASK_AUTHORIZATION_REVOKED' THEN child.causation_event_id
         ELSE (
             SELECT r.causation_event_id
             FROM cti_events r
             WHERE r.event_id = child.causation_event_id
               AND r.event_type = 'TASK_AUTHORIZATION_REVOKED'
             LIMIT 1
         )
     END
     LIMIT 1
 )
WHERE child.mission_id = @stage286_revocation_mission_id
  AND child.event_type IN (
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_REVOCATION_STOP_REQUESTED'
  )
  AND NOT (child.upstream_event_id <=> ingress.upstream_event_id);

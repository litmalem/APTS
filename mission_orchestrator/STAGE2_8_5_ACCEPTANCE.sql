-- Stage 2.8.5 acceptance queries
-- Run AFTER deploying Stage 2.8.5, restarting VulnDesk, and starting a fresh mission.
-- Replace the value below with the fresh mission id.
SET @stage285_mission_id = 'REPLACE-WITH-STAGE285-MISSION-ID';

-- A. Show task lifecycle events and their first-class lineage.
SELECT
    e.id,
    e.event_id,
    e.event_schema_version,
    e.mission_id,
    e.event_type,
    e.trace_id,
    e.proposal_id,
    e.task_id,
    e.policy_decision_id,
    e.authorization_request_id,
    e.revalidation_id,
    e.created_at
FROM cti_events e
WHERE e.mission_id = @stage285_mission_id
  AND e.event_type IN (
      'TASK_COMMITTED',
      'TASK_AUTHORIZATION_REVALIDATED',
      'TASK_DISPATCHED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_REVOCATION_STOP_REQUESTED',
      'TASK_COMPLETED',
      'TASK_FAILED'
  )
ORDER BY e.id;

-- B. Canonical TaskContract identity mismatch. Expected: 0 rows.
-- Historical pre-2.8.5 events are excluded by mission scope.
SELECT
    e.event_id,
    e.event_type,
    e.task_id AS event_task_id,
    t.task_id AS contract_task_id,
    e.trace_id AS event_trace_id,
    t.trace_id AS contract_trace_id,
    e.proposal_id,
    e.policy_decision_id AS event_policy_decision_id,
    t.policy_decision_id AS contract_policy_decision_id,
    e.authorization_request_id AS event_request_id,
    t.authorization_request_id AS contract_request_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
WHERE e.mission_id = @stage285_mission_id
  AND e.event_type IN (
      'TASK_COMMITTED',
      'TASK_AUTHORIZATION_REVALIDATED',
      'TASK_DISPATCHED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_REVOCATION_STOP_REQUESTED',
      'TASK_COMPLETED',
      'TASK_FAILED'
  )
  AND (
      e.event_schema_version <> 'cti-event-v2'
      OR e.task_id IS NULL OR TRIM(e.task_id) = ''
      OR e.trace_id IS NULL OR TRIM(e.trace_id) = ''
      OR e.proposal_id IS NULL OR TRIM(e.proposal_id) = ''
      OR e.trace_id <> t.trace_id
      OR e.proposal_id <> t.trace_id
      OR NOT (e.policy_decision_id <=> t.policy_decision_id)
      OR NOT (e.authorization_request_id <=> t.authorization_request_id)
  );

-- C. Internal tasks must not manufacture external authority. Expected: 0 rows.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    t.authorization_mode,
    e.policy_decision_id,
    e.authorization_request_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
WHERE e.mission_id = @stage285_mission_id
  AND t.authorization_mode = 'NOT_REQUIRED_INTERNAL'
  AND e.event_type IN ('TASK_COMMITTED','TASK_DISPATCHED','TASK_COMPLETED','TASK_FAILED')
  AND (e.policy_decision_id IS NOT NULL OR e.authorization_request_id IS NOT NULL);

-- D. Required-authority lifecycle must retain exact binding. Expected: 0 rows.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    t.authorization_mode,
    e.policy_decision_id,
    t.policy_decision_id,
    e.authorization_request_id,
    t.authorization_request_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
WHERE e.mission_id = @stage285_mission_id
  AND t.authorization_mode = 'REQUIRED'
  AND e.event_type IN (
      'TASK_COMMITTED',
      'TASK_AUTHORIZATION_REVALIDATED',
      'TASK_DISPATCHED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_REVOCATION_STOP_REQUESTED'
  )
  AND (
      e.policy_decision_id IS NULL
      OR e.authorization_request_id IS NULL
      OR e.policy_decision_id <> t.policy_decision_id
      OR e.authorization_request_id <> t.authorization_request_id
  );

-- E. Revalidation event must expose the exact persisted revalidation id. Expected: 0 rows.
SELECT
    e.event_id,
    e.event_type,
    e.task_id,
    e.revalidation_id AS event_revalidation_id,
    t.pre_dispatch_revalidation_id AS contract_revalidation_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
WHERE e.mission_id = @stage285_mission_id
  AND e.event_type IN ('TASK_AUTHORIZATION_REVALIDATED','TASK_DISPATCHED','TASK_DISPATCH_BLOCKED')
  AND t.authorization_mode = 'REQUIRED'
  AND t.pre_dispatch_revalidation_id IS NOT NULL
  AND NOT (e.revalidation_id <=> t.pre_dispatch_revalidation_id);

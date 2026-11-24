-- Stage 2.8.4 acceptance probes -- TASK_COMMITTED lineage
USE `vulndesk`;

-- A. Recent TASK_COMMITTED events should expose first-class lineage.
SELECT
    id,
    event_id,
    event_schema_version,
    mission_id,
    event_type,
    trace_id,
    proposal_id,
    task_id,
    policy_decision_id,
    authorization_request_id,
    policy_version,
    JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.authorization_mode')) AS authorization_mode,
    JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.scope_contract_id')) AS scope_contract_id,
    created_at
FROM cti_events
WHERE event_type = 'TASK_COMMITTED'
ORDER BY id DESC
LIMIT 50;

-- B. Canonical Stage 2.8.4 lineage invariant. Expected: 0 rows.
SELECT
    event_id, mission_id, trace_id, proposal_id, task_id, event_schema_version
FROM cti_events
WHERE event_type = 'TASK_COMMITTED'
  AND (
      event_schema_version <> 'cti-event-v2'
      OR trace_id IS NULL OR TRIM(trace_id) = ''
      OR proposal_id IS NULL OR TRIM(proposal_id) = ''
      OR task_id IS NULL OR TRIM(task_id) = ''
      OR trace_id <> proposal_id
  );

-- C. REQUIRED task must expose exact authoritative references. Expected: 0 rows.
SELECT
    event_id, mission_id, task_id, policy_decision_id, authorization_request_id, payload_json
FROM cti_events
WHERE event_type = 'TASK_COMMITTED'
  AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.authorization_mode')) = 'REQUIRED'
  AND (
      policy_decision_id IS NULL OR TRIM(policy_decision_id) = ''
      OR authorization_request_id IS NULL OR TRIM(authorization_request_id) = ''
      OR JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.scope_contract_id')) IS NULL
  );

-- D. Internal tasks must not manufacture external authority. Expected: 0 rows.
SELECT
    event_id, mission_id, task_id, policy_decision_id, authorization_request_id, payload_json
FROM cti_events
WHERE event_type = 'TASK_COMMITTED'
  AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.authorization_mode')) = 'NOT_REQUIRED_INTERNAL'
  AND (policy_decision_id IS NOT NULL OR authorization_request_id IS NOT NULL);

-- E. Event-to-TaskContract identity/binding consistency. Expected: 0 rows.
SELECT
    e.event_id,
    e.mission_id,
    e.trace_id AS event_trace_id,
    t.trace_id AS task_trace_id,
    e.task_id,
    e.policy_decision_id AS event_policy_decision_id,
    t.policy_decision_id AS task_policy_decision_id,
    e.authorization_request_id AS event_request_id,
    t.authorization_request_id AS task_request_id
FROM cti_events e
JOIN cti_task_contracts t ON t.task_id = e.task_id
WHERE e.event_type = 'TASK_COMMITTED'
  AND (
      e.mission_id <> t.mission_id
      OR e.trace_id <> t.trace_id
      OR NOT (e.policy_decision_id <=> t.policy_decision_id)
      OR NOT (e.authorization_request_id <=> t.authorization_request_id)
  );

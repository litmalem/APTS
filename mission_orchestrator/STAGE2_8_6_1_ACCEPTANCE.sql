-- Stage 2.8.6.1 Revocation/Pre-dispatch Race Hardening acceptance
-- Run after a fresh gated revocation mission on the patched runtime.
USE `vulndesk`;

SET @stage2861_mission_id = 'REPLACE-WITH-STAGE2861-REVOCATION-MISSION-ID';

-- A. Exact governed task should remain revocation-specific after failed revalidation.
SELECT
    task_id,
    mission_id,
    status,
    authorization_mode,
    policy_decision_id,
    authorization_request_id,
    revocation_id,
    revocation_event_id,
    revocation_status,
    revoked_at,
    revocation_verified_at,
    pre_dispatch_revalidation_id,
    pre_dispatch_revalidation_status,
    dispatch_authorized_at,
    dispatch_blocked_at
FROM cti_task_contracts
WHERE mission_id = @stage2861_mission_id
  AND authorization_mode = 'REQUIRED'
ORDER BY id;

-- B. Revoked governed tasks must not be downgraded to generic authorization blocks. Expected: 0 rows.
SELECT
    task_id,
    status,
    revocation_status,
    revoked_at,
    dispatch_authorized_at,
    dispatch_blocked_at
FROM cti_task_contracts
WHERE mission_id = @stage2861_mission_id
  AND authorization_mode = 'REQUIRED'
  AND (
      revocation_status LIKE 'VERIFIED_REVOKED%'
      OR revocation_status LIKE 'FAIL_CLOSED%'
      OR revoked_at IS NOT NULL
  )
  AND status <> 'BLOCKED_REVOKED';

-- C. Positive cross-subsystem causal chain.
SELECT
    e.id,
    e.event_type,
    e.event_id,
    e.task_id,
    e.policy_decision_id,
    e.causation_event_id,
    p.event_type AS parent_event_type,
    e.upstream_event_id,
    e.created_at
FROM cti_events e
LEFT JOIN cti_events p
       ON p.event_id = e.causation_event_id
WHERE e.mission_id = @stage2861_mission_id
  AND e.event_type IN (
      'AUTHORIZATION_REVOKED',
      'TASK_AUTHORIZATION_REVOKED',
      'TASK_DISPATCH_BLOCKED',
      'TASK_REVOCATION_STOP_REQUESTED',
      'TASK_DISPATCHED'
  )
ORDER BY e.id;

-- D. AUTHORIZATION_REVOKED ingress must retain gevent-* upstream. Expected: 0 rows.
SELECT event_id, upstream_event_id
FROM cti_events
WHERE mission_id = @stage2861_mission_id
  AND event_type = 'AUTHORIZATION_REVOKED'
  AND (
      upstream_event_id IS NULL
      OR upstream_event_id NOT LIKE 'gevent-%'
  );

-- E. Task revoke must be caused by local ingress and preserve same upstream. Expected: 0 rows.
SELECT
    child.event_id,
    child.task_id,
    child.causation_event_id,
    parent.event_type AS parent_event_type,
    child.upstream_event_id,
    parent.upstream_event_id AS parent_upstream_event_id
FROM cti_events child
LEFT JOIN cti_events parent
       ON parent.event_id = child.causation_event_id
WHERE child.mission_id = @stage2861_mission_id
  AND child.event_type = 'TASK_AUTHORIZATION_REVOKED'
  AND (
      child.causation_event_id IS NULL
      OR parent.event_type <> 'AUTHORIZATION_REVOKED'
      OR NOT (child.upstream_event_id <=> parent.upstream_event_id)
  );

-- F. Revocation dispatch block must be caused by TASK_AUTHORIZATION_REVOKED. Expected: 0 rows.
SELECT
    child.event_id,
    child.task_id,
    child.causation_event_id,
    parent.event_type AS parent_event_type,
    child.upstream_event_id,
    parent.upstream_event_id AS parent_upstream_event_id
FROM cti_events child
LEFT JOIN cti_events parent
       ON parent.event_id = child.causation_event_id
WHERE child.mission_id = @stage2861_mission_id
  AND child.event_type = 'TASK_DISPATCH_BLOCKED'
  AND child.upstream_event_id LIKE 'gevent-%'
  AND (
      child.causation_event_id IS NULL
      OR parent.event_type <> 'TASK_AUTHORIZATION_REVOKED'
      OR NOT (child.upstream_event_id <=> parent.upstream_event_id)
  );

-- G. No successful dispatch may occur after authoritative revocation ingress. Expected: 0 rows.
SELECT
    d.event_id AS dispatched_event_id,
    d.task_id,
    d.created_at AS dispatched_at,
    r.event_id AS revoke_ingress_event_id,
    r.created_at AS revoked_ingress_at
FROM cti_events d
JOIN cti_events r
  ON r.mission_id = d.mission_id
 AND r.event_type = 'AUTHORIZATION_REVOKED'
WHERE d.mission_id = @stage2861_mission_id
  AND d.event_type = 'TASK_DISPATCHED'
  AND d.id > r.id;

-- H. Durable revocation ledger using actual Stage 2.7 schema.
SELECT
    revocation_id,
    governance_event_id,
    local_event_id,
    decision_id,
    request_id,
    mission_id,
    decision_status,
    revocation_scope,
    verification_status,
    verification_error,
    affected_task_count,
    active_affected_count,
    revoked_at,
    received_at,
    verified_at
FROM cti_policy_decision_revocations
WHERE mission_id = @stage2861_mission_id
ORDER BY id;

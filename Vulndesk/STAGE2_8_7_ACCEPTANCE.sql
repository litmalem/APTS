-- ============================================================================
-- VulnDesk Stage 2.8.7 -- Decision / Audit Lineage Acceptance
-- Requires Stage 2.8 migration 07 already applied.
-- No new schema migration is required for Stage 2.8.7.
--
-- Set this to a FRESH acceptance mission generated after installing 2.8.7.
-- ============================================================================
USE `vulndesk`;
SET @stage287_mission_id = 'MISSION-STAGE287-ANDA';

-- A. Positive reconstruction view.
-- Arbitration rows may legitimately have downstream_event_ref=NULL because
-- they precede task commit. Task-bound decision rows must point to a CTI event.
SELECT
    d.id,
    d.trace_id AS decision_trace_id,
    d.decision_type,
    d.lineage_trace_id,
    d.proposal_id,
    d.task_id,
    d.policy_decision_id,
    d.authorization_request_id,
    d.revalidation_id,
    a.audit_id,
    a.downstream_event_ref,
    e.event_type AS downstream_event_type,
    e.trace_id AS event_trace_id,
    e.task_id AS event_task_id,
    e.policy_decision_id AS event_policy_decision_id,
    e.authorization_request_id AS event_authorization_request_id,
    e.revalidation_id AS event_revalidation_id,
    d.created_at
FROM cti_decision_traces d
LEFT JOIN cti_audit_log a
       ON a.trace_id = d.trace_id
      AND a.mission_id = d.mission_id
      AND a.event_type LIKE 'orchestration.decision.%'
LEFT JOIN cti_events e
       ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
ORDER BY d.id;

-- B. Task-bound decision lineage must resolve to the exact TaskContract.
-- EXPECTED: 0 rows.
SELECT
    d.trace_id,
    d.decision_type,
    d.lineage_trace_id,
    d.proposal_id,
    d.task_id,
    d.policy_decision_id,
    d.authorization_request_id,
    d.revalidation_id,
    t.trace_id AS contract_trace_id,
    t.policy_decision_id AS contract_policy_decision_id,
    t.authorization_request_id AS contract_authorization_request_id,
    t.pre_dispatch_revalidation_id AS contract_revalidation_id
FROM cti_decision_traces d
LEFT JOIN cti_task_contracts t
       ON t.task_id = d.task_id
WHERE d.mission_id = @stage287_mission_id
  AND d.task_id IS NOT NULL
  AND (
       t.task_id IS NULL
       OR d.lineage_trace_id IS NULL
       OR d.proposal_id IS NULL
       OR d.lineage_trace_id <> d.proposal_id
       OR d.lineage_trace_id <> t.trace_id
       OR NOT (d.policy_decision_id <=> t.policy_decision_id)
       OR NOT (d.authorization_request_id <=> t.authorization_request_id)
       OR (
            d.revalidation_id IS NOT NULL
            AND NOT (d.revalidation_id <=> t.pre_dispatch_revalidation_id)
          )
  );

-- C. Every Stage 2.8.7 decision audit row must resolve to its decision trace.
-- EXPECTED: 0 rows.
SELECT
    a.audit_id,
    a.mission_id,
    a.event_type,
    a.trace_id,
    a.downstream_event_ref
FROM cti_audit_log a
LEFT JOIN cti_decision_traces d
       ON d.trace_id = a.trace_id
      AND d.mission_id = a.mission_id
WHERE a.mission_id = @stage287_mission_id
  AND a.event_type LIKE 'orchestration.decision.%'
  AND d.trace_id IS NULL;

-- D. Every non-arbitration decision trace must have a valid downstream CTI
-- event in the same mission. EXPECTED: 0 rows.
SELECT
    d.trace_id,
    d.decision_type,
    d.task_id,
    a.audit_id,
    a.downstream_event_ref,
    e.mission_id AS event_mission_id,
    e.event_type
FROM cti_decision_traces d
LEFT JOIN cti_audit_log a
       ON a.trace_id = d.trace_id
      AND a.mission_id = d.mission_id
      AND a.event_type LIKE 'orchestration.decision.%'
LEFT JOIN cti_events e
       ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type <> 'ARBITRATION'
  AND (
       a.audit_id IS NULL
       OR a.downstream_event_ref IS NULL
       OR e.event_id IS NULL
       OR e.mission_id <> d.mission_id
  );

-- E1. Positive TASK_COMMIT trace -> audit -> TASK_COMMITTED event.
SELECT
    d.trace_id AS decision_trace_id,
    d.lineage_trace_id,
    d.proposal_id,
    d.task_id,
    d.policy_decision_id,
    d.authorization_request_id,
    a.audit_id,
    a.downstream_event_ref,
    e.event_type,
    e.trace_id,
    e.proposal_id AS event_proposal_id,
    e.task_id AS event_task_id,
    e.policy_decision_id AS event_policy_decision_id,
    e.authorization_request_id AS event_authorization_request_id
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type = 'TASK_COMMIT'
ORDER BY d.id;

-- E2. TASK_COMMIT mismatch. EXPECTED: 0 rows.
SELECT d.trace_id, d.task_id, a.downstream_event_ref, e.event_type
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
LEFT JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type = 'TASK_COMMIT'
  AND (
       e.event_id IS NULL
       OR e.event_type <> 'TASK_COMMITTED'
       OR e.task_id <> d.task_id
       OR e.trace_id <> d.lineage_trace_id
       OR e.proposal_id <> d.proposal_id
       OR NOT (e.policy_decision_id <=> d.policy_decision_id)
       OR NOT (e.authorization_request_id <=> d.authorization_request_id)
  );

-- F1. Positive governed PRE_DISPATCH_REVALIDATION lineage.
SELECT
    d.trace_id AS decision_trace_id,
    d.task_id,
    d.policy_decision_id,
    d.authorization_request_id,
    d.revalidation_id,
    a.downstream_event_ref,
    e.event_type,
    e.causation_event_id,
    e.revalidation_id AS event_revalidation_id
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type = 'PRE_DISPATCH_REVALIDATION'
ORDER BY d.id;

-- F2. PRE_DISPATCH_REVALIDATION mismatch. EXPECTED: 0 rows.
SELECT d.trace_id, d.task_id, d.revalidation_id, a.downstream_event_ref, e.event_type
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
LEFT JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type = 'PRE_DISPATCH_REVALIDATION'
  AND (
       e.event_id IS NULL
       OR e.event_type NOT IN ('TASK_AUTHORIZATION_REVALIDATED','TASK_DISPATCH_BLOCKED')
       OR e.task_id <> d.task_id
       OR e.trace_id <> d.lineage_trace_id
       OR NOT (e.policy_decision_id <=> d.policy_decision_id)
       OR NOT (e.authorization_request_id <=> d.authorization_request_id)
       OR NOT (e.revalidation_id <=> d.revalidation_id)
  );

-- G1. Positive TASK_RESULT / safety-enforcement decision lineage.
SELECT
    d.trace_id AS decision_trace_id,
    d.decision_type,
    d.task_id,
    d.policy_decision_id,
    d.revalidation_id,
    a.downstream_event_ref,
    e.event_type,
    e.causation_event_id,
    e.upstream_event_id
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type IN (
      'TASK_RESULT',
      'AUTHORIZATION_REVOCATION',
      'DISPATCH_BLOCK',
      'REVOCATION_STOP'
  )
ORDER BY d.id;

-- G2. Result/safety decision downstream mismatch. EXPECTED: 0 rows.
SELECT d.trace_id, d.decision_type, d.task_id, a.downstream_event_ref, e.event_type
FROM cti_decision_traces d
JOIN cti_audit_log a
  ON a.trace_id = d.trace_id
 AND a.mission_id = d.mission_id
LEFT JOIN cti_events e
  ON e.event_id = a.downstream_event_ref
WHERE d.mission_id = @stage287_mission_id
  AND d.decision_type IN (
      'TASK_RESULT',
      'AUTHORIZATION_REVOCATION',
      'DISPATCH_BLOCK',
      'REVOCATION_STOP'
  )
  AND (
       e.event_id IS NULL
       OR e.task_id <> d.task_id
       OR e.trace_id <> d.lineage_trace_id
       OR NOT (e.policy_decision_id <=> d.policy_decision_id)
       OR NOT (e.authorization_request_id <=> d.authorization_request_id)
       OR (
            d.revalidation_id IS NOT NULL
            AND NOT (e.revalidation_id <=> d.revalidation_id)
          )
  );

-- H. Authority boundary must remain intact.
-- H1 internal decision traces must not manufacture Governance authority.
-- EXPECTED: 0 rows.
SELECT d.trace_id, d.decision_type, d.task_id, d.policy_decision_id, d.authorization_request_id
FROM cti_decision_traces d
JOIN cti_task_contracts t ON t.task_id = d.task_id
WHERE d.mission_id = @stage287_mission_id
  AND t.authorization_mode = 'NOT_REQUIRED_INTERNAL'
  AND (
      d.policy_decision_id IS NOT NULL
      OR d.authorization_request_id IS NOT NULL
  );

-- H2 REQUIRED task-bound decision traces must preserve the authoritative binding.
-- EXPECTED: 0 rows.
SELECT d.trace_id, d.decision_type, d.task_id
FROM cti_decision_traces d
JOIN cti_task_contracts t ON t.task_id = d.task_id
WHERE d.mission_id = @stage287_mission_id
  AND t.authorization_mode = 'REQUIRED'
  AND (
      d.policy_decision_id IS NULL
      OR d.authorization_request_id IS NULL
      OR d.policy_decision_id <> t.policy_decision_id
      OR d.authorization_request_id <> t.authorization_request_id
  );

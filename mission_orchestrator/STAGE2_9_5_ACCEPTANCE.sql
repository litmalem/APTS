/*
Stage 2.9.5 — Integrity / Violation Probe Acceptance

MariaDB databases from the supplied baseline:
  vulndesk
  apts_governance

Set @mission_id to the SAME FRESH governed mission used with
STAGE2_9_5_ACCEPTANCE.ps1.

This SQL independently checks the four canonical Stage 2.9.5 invariants from persisted
records and also reports a positive revocation-enforcement pattern. The runtime HTTP probe
remains the authoritative Stage 2.9.5 application acceptance because it combines canonical
lineage reconstruction with the Stage 2.9.4 service-boundary correlation snapshot.
*/

SET @mission_id = 'REPLACE_WITH_FRESH_MISSION_ID';

/* -------------------------------------------------------------------------
   1. Mission TaskContracts and their Governance bindings.
   ------------------------------------------------------------------------- */
SELECT
    task_id,
    mission_id,
    assigned_component,
    task_type,
    status,
    authorization_mode,
    policy_decision_id,
    authorization_request_id,
    scope_contract_id,
    scope_version,
    authorization_governance_event_id,
    pre_dispatch_governance_event_id,
    revocation_event_id,
    revocation_status,
    dispatch_authorized_at,
    dispatch_blocked_at,
    created_at,
    updated_at
FROM vulndesk.cti_task_contracts
WHERE mission_id = @mission_id
ORDER BY id;

/* -------------------------------------------------------------------------
   2. Canonical task lifecycle event stream.
   ------------------------------------------------------------------------- */
SELECT
    id AS db_sequence,
    event_id,
    event_type,
    task_id,
    policy_decision_id,
    authorization_request_id,
    revalidation_id,
    causation_event_id,
    upstream_event_id,
    created_at
FROM vulndesk.cti_events
WHERE mission_id = @mission_id
  AND task_id IS NOT NULL
ORDER BY id;

/* -------------------------------------------------------------------------
   INV-295-01: governed dispatch without exact PolicyDecision binding.
   Expected rows: 0
   ------------------------------------------------------------------------- */
SELECT
    t.task_id,
    t.authorization_mode,
    t.policy_decision_id AS task_policy_decision_id,
    e.event_id AS dispatch_event_id,
    e.policy_decision_id AS dispatch_policy_decision_id,
    'DISPATCH_WITHOUT_POLICY_DECISION' AS violation_code
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events e
  ON e.mission_id = t.mission_id
 AND e.task_id = t.task_id
 AND e.event_type = 'TASK_DISPATCHED'
WHERE t.mission_id = @mission_id
  AND t.authorization_mode = 'REQUIRED'
  AND (
        t.policy_decision_id IS NULL OR t.policy_decision_id = ''
        OR e.policy_decision_id IS NULL OR e.policy_decision_id = ''
        OR e.policy_decision_id <> t.policy_decision_id
      )
ORDER BY t.id, e.id;

/* -------------------------------------------------------------------------
   INV-295-02: TASK_DISPATCHED after TASK_AUTHORIZATION_REVOKED.
   Expected rows: 0
   ------------------------------------------------------------------------- */
SELECT DISTINCT
    t.task_id,
    r.event_id AS revocation_event_id,
    r.id AS revocation_db_sequence,
    d.event_id AS dispatch_event_id,
    d.id AS dispatch_db_sequence,
    'DISPATCH_AFTER_REVOCATION' AS violation_code
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events r
  ON r.mission_id = t.mission_id
 AND r.task_id = t.task_id
 AND r.event_type = 'TASK_AUTHORIZATION_REVOKED'
JOIN vulndesk.cti_events d
  ON d.mission_id = t.mission_id
 AND d.task_id = t.task_id
 AND d.event_type = 'TASK_DISPATCHED'
 AND d.id > r.id
WHERE t.mission_id = @mission_id
ORDER BY t.task_id, r.id, d.id;

/* -------------------------------------------------------------------------
   INV-295-03: TaskContract scope differs from authoritative PolicyDecision scope.
   Expected rows: 0
   ------------------------------------------------------------------------- */
SELECT
    t.task_id,
    t.policy_decision_id,
    t.scope_contract_id AS task_scope_contract_id,
    d.scope_contract_id AS authoritative_policy_scope_contract_id,
    d.decision,
    d.decision_status,
    'TASK_SCOPE_POLICY_SCOPE_MISMATCH' AS violation_code
FROM vulndesk.cti_task_contracts t
JOIN apts_governance.gov_policy_decisions d
  ON d.decision_id = t.policy_decision_id
WHERE t.mission_id = @mission_id
  AND t.authorization_mode = 'REQUIRED'
  AND COALESCE(t.scope_contract_id, '') <> COALESCE(d.scope_contract_id, '')
ORDER BY t.id;

/* -------------------------------------------------------------------------
   INV-295-04a: TaskContract status COMPLETED but no TASK_DISPATCHED exists.
   Expected rows: 0
   ------------------------------------------------------------------------- */
SELECT
    t.task_id,
    t.status,
    'COMPLETED_WITHOUT_DISPATCHED' AS violation_code
FROM vulndesk.cti_task_contracts t
WHERE t.mission_id = @mission_id
  AND t.status = 'COMPLETED'
  AND NOT EXISTS (
        SELECT 1
        FROM vulndesk.cti_events d
        WHERE d.mission_id = t.mission_id
          AND d.task_id = t.task_id
          AND d.event_type = 'TASK_DISPATCHED'
      )
ORDER BY t.id;

/* -------------------------------------------------------------------------
   INV-295-04b: completion event occurs before any prior dispatch.
   Expected rows: 0
   ------------------------------------------------------------------------- */
SELECT DISTINCT
    c.task_id,
    c.event_id AS completion_event_id,
    c.event_type AS completion_event_type,
    c.id AS completion_db_sequence,
    'COMPLETED_WITHOUT_DISPATCHED' AS violation_code
FROM vulndesk.cti_events c
WHERE c.mission_id = @mission_id
  AND c.task_id IS NOT NULL
  AND c.event_type IN ('TASK_COMPLETED', 'SOURCE_SYNC_COMPLETED')
  AND NOT EXISTS (
        SELECT 1
        FROM vulndesk.cti_events d
        WHERE d.mission_id = c.mission_id
          AND d.task_id = c.task_id
          AND d.event_type = 'TASK_DISPATCHED'
          AND d.id < c.id
      )
ORDER BY c.id;

/* -------------------------------------------------------------------------
   Positive control: correct blocking after revocation.
   These are NOT violations. Rows are expected only for a revocation scenario.
   ------------------------------------------------------------------------- */
SELECT DISTINCT
    t.task_id,
    t.status,
    r.event_id AS revocation_event_id,
    b.event_id AS blocked_event_id,
    CASE
      WHEN NOT EXISTS (
        SELECT 1
        FROM vulndesk.cti_events d
        WHERE d.mission_id=t.mission_id
          AND d.task_id=t.task_id
          AND d.event_type='TASK_DISPATCHED'
          AND d.id > r.id
      ) THEN 'CORRECTLY_BLOCKED_AFTER_REVOCATION'
      ELSE 'INVALID_DISPATCH_AFTER_REVOCATION'
    END AS enforcement_classification
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events r
  ON r.mission_id=t.mission_id
 AND r.task_id=t.task_id
 AND r.event_type='TASK_AUTHORIZATION_REVOKED'
JOIN vulndesk.cti_events b
  ON b.mission_id=t.mission_id
 AND b.task_id=t.task_id
 AND b.event_type='TASK_DISPATCH_BLOCKED'
 AND b.id > r.id
WHERE t.mission_id=@mission_id
ORDER BY t.task_id;

/* -------------------------------------------------------------------------
   Cross-subsystem authority availability checks inherited from Stage 2.9.4.
   Expected unresolved rows: 0 for a fully verifiable governed mission.
   ------------------------------------------------------------------------- */
SELECT
    t.task_id,
    t.policy_decision_id,
    CASE WHEN d.decision_id IS NULL THEN 'MISSING' ELSE 'RESOLVED' END AS policy_decision_resolution,
    t.authorization_request_id,
    CASE WHEN r.request_id IS NULL THEN 'MISSING' ELSE 'RESOLVED' END AS request_resolution,
    t.scope_contract_id,
    CASE WHEN s.scope_contract_id IS NULL THEN 'MISSING' ELSE 'RESOLVED' END AS scope_resolution
FROM vulndesk.cti_task_contracts t
LEFT JOIN apts_governance.gov_policy_decisions d
       ON d.decision_id=t.policy_decision_id
LEFT JOIN apts_governance.gov_authorization_requests r
       ON r.request_id=t.authorization_request_id
LEFT JOIN apts_governance.gov_scope_contracts s
       ON s.scope_contract_id=t.scope_contract_id
WHERE t.mission_id=@mission_id
  AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

/* -------------------------------------------------------------------------
   Acceptance summary. All violation counts must be 0 for a positive mission.
   ------------------------------------------------------------------------- */
SELECT
    @mission_id AS mission_id,
    (SELECT COUNT(*)
       FROM vulndesk.cti_task_contracts t
      WHERE t.mission_id=@mission_id) AS task_count,
    (SELECT COUNT(*)
       FROM vulndesk.cti_task_contracts t
      WHERE t.mission_id=@mission_id AND t.authorization_mode='REQUIRED') AS governed_task_count,

    /* INV-295-01 */
    (SELECT COUNT(DISTINCT t.task_id)
       FROM vulndesk.cti_task_contracts t
       JOIN vulndesk.cti_events e
         ON e.mission_id=t.mission_id AND e.task_id=t.task_id AND e.event_type='TASK_DISPATCHED'
      WHERE t.mission_id=@mission_id
        AND t.authorization_mode='REQUIRED'
        AND (
             t.policy_decision_id IS NULL OR t.policy_decision_id=''
             OR e.policy_decision_id IS NULL OR e.policy_decision_id=''
             OR e.policy_decision_id<>t.policy_decision_id
        )) AS dispatched_without_policydecision_count,

    /* INV-295-02 */
    (SELECT COUNT(DISTINCT t.task_id)
       FROM vulndesk.cti_task_contracts t
       JOIN vulndesk.cti_events r
         ON r.mission_id=t.mission_id AND r.task_id=t.task_id AND r.event_type='TASK_AUTHORIZATION_REVOKED'
       JOIN vulndesk.cti_events d
         ON d.mission_id=t.mission_id AND d.task_id=t.task_id AND d.event_type='TASK_DISPATCHED' AND d.id>r.id
      WHERE t.mission_id=@mission_id) AS dispatched_after_revocation_count,

    /* INV-295-03 */
    (SELECT COUNT(DISTINCT t.task_id)
       FROM vulndesk.cti_task_contracts t
       JOIN apts_governance.gov_policy_decisions d ON d.decision_id=t.policy_decision_id
      WHERE t.mission_id=@mission_id
        AND t.authorization_mode='REQUIRED'
        AND COALESCE(t.scope_contract_id,'')<>COALESCE(d.scope_contract_id,'')) AS task_scope_policy_scope_mismatch_count,

    /* INV-295-04 */
    (SELECT COUNT(DISTINCT x.task_id)
       FROM (
            SELECT t.task_id
              FROM vulndesk.cti_task_contracts t
             WHERE t.mission_id=@mission_id
               AND t.status='COMPLETED'
               AND NOT EXISTS (
                    SELECT 1 FROM vulndesk.cti_events d
                     WHERE d.mission_id=t.mission_id
                       AND d.task_id=t.task_id
                       AND d.event_type='TASK_DISPATCHED'
               )
            UNION
            SELECT c.task_id
              FROM vulndesk.cti_events c
             WHERE c.mission_id=@mission_id
               AND c.task_id IS NOT NULL
               AND c.event_type IN ('TASK_COMPLETED','SOURCE_SYNC_COMPLETED')
               AND NOT EXISTS (
                    SELECT 1 FROM vulndesk.cti_events d
                     WHERE d.mission_id=c.mission_id
                       AND d.task_id=c.task_id
                       AND d.event_type='TASK_DISPATCHED'
                       AND d.id<c.id
               )
       ) x) AS completed_without_dispatched_count,

    /* Stage 2.9.4 authoritative resolution needed for verification_complete=true. */
    (SELECT COUNT(*)
       FROM vulndesk.cti_task_contracts t
       LEFT JOIN apts_governance.gov_policy_decisions d ON d.decision_id=t.policy_decision_id
      WHERE t.mission_id=@mission_id
        AND t.authorization_mode='REQUIRED'
        AND d.decision_id IS NULL) AS unresolved_policydecision_count,

    (SELECT COUNT(*)
       FROM vulndesk.cti_task_contracts t
       LEFT JOIN apts_governance.gov_authorization_requests r ON r.request_id=t.authorization_request_id
      WHERE t.mission_id=@mission_id
        AND t.authorization_mode='REQUIRED'
        AND r.request_id IS NULL) AS unresolved_authorization_request_count,

    (SELECT COUNT(*)
       FROM vulndesk.cti_task_contracts t
       LEFT JOIN apts_governance.gov_scope_contracts s ON s.scope_contract_id=t.scope_contract_id
      WHERE t.mission_id=@mission_id
        AND t.authorization_mode='REQUIRED'
        AND s.scope_contract_id IS NULL) AS unresolved_scope_contract_count;

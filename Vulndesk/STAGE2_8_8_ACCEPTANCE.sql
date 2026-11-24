-- ============================================================================
-- Stage 2.8.8 — Cross-Subsystem Enrichment / Acceptance
-- Databases: apts_governance + vulndesk
--
-- Set BOTH variables to fresh post-2.8.8 missions before running.
-- Governed mission: normal REQUIRED authorization + pre-dispatch revalidation.
-- Revocation mission: exact PolicyDecision revoked before dispatch.
-- ============================================================================
SET @stage288_governed_mission_id =
    'MISSION-STAGE288-GOVERNED-TO-REPLACE';
SET @stage288_revocation_mission_id =
    'MISSION-STAGE288-REVOCATION-TO-REPLACE';

-- A. Migration readiness. EXPECTED: 4 rows.
SELECT table_name, column_name, column_type
FROM information_schema.columns
WHERE table_schema='vulndesk'
  AND (
       (table_name='cti_task_contracts'
        AND column_name IN (
          'authorization_governance_event_id',
          'pre_dispatch_governance_event_id'))
    OR (table_name='cti_decision_traces'
        AND column_name='upstream_event_id')
    OR (table_name='cti_audit_log'
        AND column_name='upstream_event_ref')
  )
ORDER BY table_name,column_name;

-- ============================================================================
-- B. POLICY_DECISION_ISSUED: authoritative outbox -> TaskContract
-- ============================================================================

-- B1 positive. EXPECTED >=1.
SELECT
 t.task_id,t.authorization_mode,
 t.authorization_governance_event_id,
 t.policy_decision_id,t.authorization_request_id,
 g.event_type,g.delivery_status,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.governance_event_id'))
   AS payload_governance_event_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.decision_id'))
   AS payload_decision_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.request_id'))
   AS payload_request_id
FROM vulndesk.cti_task_contracts t
JOIN apts_governance.gov_event_outbox g
 ON g.event_id=t.authorization_governance_event_id
AND g.mission_id=t.mission_id
AND g.event_type='POLICY_DECISION_ISSUED'
WHERE t.mission_id=@stage288_governed_mission_id
  AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

-- B2 mismatch/dangling. EXPECTED 0.
SELECT
 t.task_id,t.authorization_governance_event_id,
 t.policy_decision_id,t.authorization_request_id,
 g.event_id,g.event_type,g.delivery_status
FROM vulndesk.cti_task_contracts t
LEFT JOIN apts_governance.gov_event_outbox g
 ON g.event_id=t.authorization_governance_event_id
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
 AND (
      t.authorization_governance_event_id IS NULL
   OR g.event_id IS NULL
   OR g.mission_id<>t.mission_id
   OR g.event_type<>'POLICY_DECISION_ISSUED'
   OR g.delivery_status<>'DELIVERED'
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.governance_event_id'))
        <>t.authorization_governance_event_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.decision_id'))
        <>t.policy_decision_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.request_id'))
        <>t.authorization_request_id
 );

-- B3 durable local outbox ingress. EXPECTED >=1.
SELECT
 e.event_id AS local_event_id,e.event_type,e.source_component,
 e.upstream_event_id,g.event_id AS governance_event_id,g.delivery_status
FROM vulndesk.cti_events e
JOIN apts_governance.gov_event_outbox g
 ON g.event_id=e.upstream_event_id
AND g.mission_id=e.mission_id
AND g.event_type='POLICY_DECISION_ISSUED'
WHERE e.mission_id=@stage288_governed_mission_id
 AND e.event_type='POLICY_DECISION_ISSUED'
ORDER BY e.id;

-- ============================================================================
-- C. Issuance gevent -> TASK_COMMITTED -> DecisionTrace -> Audit
-- ============================================================================

-- C1 positive. EXPECTED >=1.
SELECT
 t.task_id,t.trace_id,t.authorization_governance_event_id,
 e.event_id AS task_committed_event_id,
 e.upstream_event_id AS event_upstream,
 d.trace_id AS decision_trace_id,d.upstream_event_id AS decision_upstream,
 a.audit_id,a.upstream_event_ref AS audit_upstream,
 a.downstream_event_ref
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events e
 ON e.mission_id=t.mission_id
AND e.task_id=t.task_id
AND e.event_type='TASK_COMMITTED'
JOIN vulndesk.cti_decision_traces d
 ON d.mission_id=t.mission_id
AND d.task_id=t.task_id
AND d.decision_type='TASK_COMMIT'
JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id
AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

-- C2 mismatch. EXPECTED 0.
SELECT
 t.task_id,t.authorization_governance_event_id,
 e.event_id,e.upstream_event_id,
 d.trace_id,d.upstream_event_id,
 a.audit_id,a.upstream_event_ref,a.downstream_event_ref
FROM vulndesk.cti_task_contracts t
LEFT JOIN vulndesk.cti_events e
 ON e.mission_id=t.mission_id
AND e.task_id=t.task_id
AND e.event_type='TASK_COMMITTED'
LEFT JOIN vulndesk.cti_decision_traces d
 ON d.mission_id=t.mission_id
AND d.task_id=t.task_id
AND d.decision_type='TASK_COMMIT'
LEFT JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id
AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
 AND (
      e.event_id IS NULL OR d.trace_id IS NULL OR a.audit_id IS NULL
   OR NOT(e.upstream_event_id <=> t.authorization_governance_event_id)
   OR NOT(d.upstream_event_id <=> t.authorization_governance_event_id)
   OR NOT(a.upstream_event_ref <=> t.authorization_governance_event_id)
   OR NOT(a.downstream_event_ref <=> e.event_id)
   OR NOT(e.trace_id <=> t.trace_id)
   OR NOT(d.lineage_trace_id <=> t.trace_id)
 );

-- ============================================================================
-- D. POLICY_DECISION_REVALIDATED: authoritative outbox -> all VulnDesk layers
-- ============================================================================

-- D1 positive outbox binding. EXPECTED >=1.
SELECT
 t.task_id,t.pre_dispatch_revalidation_id,
 t.pre_dispatch_governance_event_id,
 g.event_type,g.delivery_status,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.governance_event_id'))
   AS payload_governance_event_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.revalidation_id'))
   AS payload_revalidation_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.decision_id'))
   AS payload_decision_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.request_id'))
   AS payload_request_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.task_id'))
   AS payload_task_id
FROM vulndesk.cti_task_contracts t
JOIN apts_governance.gov_event_outbox g
 ON g.event_id=t.pre_dispatch_governance_event_id
AND g.mission_id=t.mission_id
AND g.event_type IN (
 'POLICY_DECISION_REVALIDATED',
 'POLICY_DECISION_REVALIDATION_FAILED')
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
 AND t.pre_dispatch_revalidation_id IS NOT NULL
ORDER BY t.id;

-- D2 outbox mismatch. EXPECTED 0.
SELECT
 t.task_id,t.pre_dispatch_revalidation_id,
 t.pre_dispatch_governance_event_id,
 g.event_id,g.event_type,g.delivery_status
FROM vulndesk.cti_task_contracts t
LEFT JOIN apts_governance.gov_event_outbox g
 ON g.event_id=t.pre_dispatch_governance_event_id
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
 AND t.pre_dispatch_revalidation_id IS NOT NULL
 AND (
      t.pre_dispatch_governance_event_id IS NULL
   OR g.event_id IS NULL
   OR g.mission_id<>t.mission_id
   OR g.event_type NOT IN(
      'POLICY_DECISION_REVALIDATED',
      'POLICY_DECISION_REVALIDATION_FAILED')
   OR g.delivery_status<>'DELIVERED'
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.governance_event_id'))
        <>t.pre_dispatch_governance_event_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.revalidation_id'))
        <>t.pre_dispatch_revalidation_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.decision_id'))
        <>t.policy_decision_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.request_id'))
        <>t.authorization_request_id
   OR JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.task_id'))
        <>t.task_id
 );

-- D3 positive CTI event + DecisionTrace + Audit. EXPECTED >=1.
SELECT
 t.task_id,t.pre_dispatch_governance_event_id,
 t.pre_dispatch_revalidation_id,
 e.event_id,e.event_type,e.upstream_event_id AS event_upstream,
 d.trace_id,d.upstream_event_id AS decision_upstream,
 a.audit_id,a.upstream_event_ref AS audit_upstream,
 a.downstream_event_ref
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events e
 ON e.mission_id=t.mission_id
AND e.task_id=t.task_id
AND e.event_type IN(
 'TASK_AUTHORIZATION_REVALIDATED','TASK_DISPATCH_BLOCKED')
AND e.revalidation_id=t.pre_dispatch_revalidation_id
JOIN vulndesk.cti_decision_traces d
 ON d.mission_id=t.mission_id
AND d.task_id=t.task_id
AND d.decision_type='PRE_DISPATCH_REVALIDATION'
AND d.revalidation_id=t.pre_dispatch_revalidation_id
JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id
AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

-- D4 mismatch. EXPECTED 0.
SELECT
 t.task_id,t.pre_dispatch_governance_event_id,
 e.event_id,e.upstream_event_id,
 d.trace_id,d.upstream_event_id,
 a.audit_id,a.upstream_event_ref,a.downstream_event_ref
FROM vulndesk.cti_task_contracts t
LEFT JOIN vulndesk.cti_events e
 ON e.mission_id=t.mission_id
AND e.task_id=t.task_id
AND e.event_type IN(
 'TASK_AUTHORIZATION_REVALIDATED','TASK_DISPATCH_BLOCKED')
AND e.revalidation_id=t.pre_dispatch_revalidation_id
LEFT JOIN vulndesk.cti_decision_traces d
 ON d.mission_id=t.mission_id
AND d.task_id=t.task_id
AND d.decision_type='PRE_DISPATCH_REVALIDATION'
AND d.revalidation_id=t.pre_dispatch_revalidation_id
LEFT JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id
AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
 AND t.pre_dispatch_revalidation_id IS NOT NULL
 AND (
      e.event_id IS NULL OR d.trace_id IS NULL OR a.audit_id IS NULL
   OR NOT(e.upstream_event_id <=> t.pre_dispatch_governance_event_id)
   OR NOT(d.upstream_event_id <=> t.pre_dispatch_governance_event_id)
   OR NOT(a.upstream_event_ref <=> t.pre_dispatch_governance_event_id)
   OR NOT(a.downstream_event_ref <=> e.event_id)
   OR NOT(e.trace_id <=> t.trace_id)
   OR NOT(d.lineage_trace_id <=> t.trace_id)
   OR NOT(e.policy_decision_id <=> t.policy_decision_id)
   OR NOT(d.policy_decision_id <=> t.policy_decision_id)
   OR NOT(e.authorization_request_id <=> t.authorization_request_id)
   OR NOT(d.authorization_request_id <=> t.authorization_request_id)
   OR NOT(e.revalidation_id <=> t.pre_dispatch_revalidation_id)
   OR NOT(d.revalidation_id <=> t.pre_dispatch_revalidation_id)
 );

-- D5 durable local revalidation outbox ingress. EXPECTED >=1.
SELECT
 e.event_id AS local_event_id,e.event_type,e.source_component,
 e.upstream_event_id,g.event_id AS governance_event_id,g.delivery_status
FROM vulndesk.cti_events e
JOIN apts_governance.gov_event_outbox g
 ON g.event_id=e.upstream_event_id
AND g.mission_id=e.mission_id
AND g.event_type=e.event_type
WHERE e.mission_id=@stage288_governed_mission_id
 AND e.event_type IN(
  'POLICY_DECISION_REVALIDATED',
  'POLICY_DECISION_REVALIDATION_FAILED')
ORDER BY e.id;

-- ============================================================================
-- E. Outbox convergence + authority boundary
-- ============================================================================

-- E1 relevant Governance outbox. EXPECTED DELIVERED.
SELECT event_id,event_type,delivery_status,attempt_count,last_error,
       delivered_at,created_at
FROM apts_governance.gov_event_outbox
WHERE mission_id=@stage288_governed_mission_id
 AND event_type IN(
  'POLICY_DECISION_ISSUED',
  'POLICY_DECISION_REVALIDATED',
  'POLICY_DECISION_REVALIDATION_FAILED')
ORDER BY id;

-- E2 undelivered. EXPECTED 0.
SELECT event_id,event_type,delivery_status,attempt_count,last_error
FROM apts_governance.gov_event_outbox
WHERE mission_id=@stage288_governed_mission_id
 AND event_type IN(
  'POLICY_DECISION_ISSUED',
  'POLICY_DECISION_REVALIDATED',
  'POLICY_DECISION_REVALIDATION_FAILED')
 AND delivery_status<>'DELIVERED';

-- E3 internal tasks manufacture Governance refs. EXPECTED 0.
SELECT task_id,authorization_mode,
 authorization_governance_event_id,
 pre_dispatch_governance_event_id,revocation_event_id
FROM vulndesk.cti_task_contracts
WHERE mission_id=@stage288_governed_mission_id
 AND authorization_mode='NOT_REQUIRED_INTERNAL'
 AND(
      authorization_governance_event_id IS NOT NULL
   OR pre_dispatch_governance_event_id IS NOT NULL
   OR revocation_event_id IS NOT NULL
 );

-- E4 dispatched REQUIRED task loses external authority refs. EXPECTED 0.
SELECT task_id,status,authorization_governance_event_id,
 pre_dispatch_governance_event_id,dispatch_authorized_at
FROM vulndesk.cti_task_contracts
WHERE mission_id=@stage288_governed_mission_id
 AND authorization_mode='REQUIRED'
 AND dispatch_authorized_at IS NOT NULL
 AND(
      authorization_governance_event_id IS NULL
   OR pre_dispatch_governance_event_id IS NULL
 );

-- ============================================================================
-- F. Unified governed reconstruction. EXPECTED >=1 coherent REQUIRED row.
-- ============================================================================
SELECT
 t.task_id,t.trace_id,t.status,
 t.policy_decision_id,t.authorization_request_id,
 t.authorization_governance_event_id,
 gi.delivery_status AS issue_delivery,
 t.pre_dispatch_revalidation_id,
 t.pre_dispatch_governance_event_id,
 gr.delivery_status AS revalidation_delivery,
 tc.event_id AS task_committed_event,
 tc.upstream_event_id AS commit_upstream,
 rv.event_id AS revalidation_event,
 rv.upstream_event_id AS revalidation_upstream,
 dc.trace_id AS task_commit_trace,
 dc.upstream_event_id AS task_commit_upstream,
 dr.trace_id AS revalidation_trace,
 dr.upstream_event_id AS revalidation_trace_upstream
FROM vulndesk.cti_task_contracts t
LEFT JOIN apts_governance.gov_event_outbox gi
 ON gi.event_id=t.authorization_governance_event_id
LEFT JOIN apts_governance.gov_event_outbox gr
 ON gr.event_id=t.pre_dispatch_governance_event_id
LEFT JOIN vulndesk.cti_events tc
 ON tc.mission_id=t.mission_id AND tc.task_id=t.task_id
AND tc.event_type='TASK_COMMITTED'
LEFT JOIN vulndesk.cti_events rv
 ON rv.mission_id=t.mission_id AND rv.task_id=t.task_id
AND rv.event_type='TASK_AUTHORIZATION_REVALIDATED'
AND rv.revalidation_id=t.pre_dispatch_revalidation_id
LEFT JOIN vulndesk.cti_decision_traces dc
 ON dc.mission_id=t.mission_id AND dc.task_id=t.task_id
AND dc.decision_type='TASK_COMMIT'
LEFT JOIN vulndesk.cti_decision_traces dr
 ON dr.mission_id=t.mission_id AND dr.task_id=t.task_id
AND dr.decision_type='PRE_DISPATCH_REVALIDATION'
WHERE t.mission_id=@stage288_governed_mission_id
 AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

-- ============================================================================
-- G. Revocation: authoritative gevent -> local causal chain -> decision/audit
-- ============================================================================

-- G1 positive outbox -> TaskContract. EXPECTED >=1.
SELECT
 t.task_id,t.status,t.policy_decision_id,t.authorization_request_id,
 t.revocation_id,t.revocation_event_id,t.revocation_status,
 t.dispatch_authorized_at,t.dispatch_blocked_at,
 g.event_type,g.delivery_status,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.governance_event_id'))
   AS payload_governance_event_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.revocation_id'))
   AS payload_revocation_id,
 JSON_UNQUOTE(JSON_EXTRACT(g.payload_json,'$.decision_id'))
   AS payload_decision_id
FROM vulndesk.cti_task_contracts t
JOIN apts_governance.gov_event_outbox g
 ON g.event_id=t.revocation_event_id
AND g.mission_id=t.mission_id
AND g.event_type='AUTHORIZATION_REVOKED'
WHERE t.mission_id=@stage288_revocation_mission_id
 AND t.authorization_mode='REQUIRED'
ORDER BY t.id;

-- G2 positive causal chain. EXPECTED >=1.
SELECT
 t.task_id,t.revocation_event_id,
 i.event_id AS ingress_event,i.upstream_event_id AS ingress_upstream,
 r.event_id AS revoked_event,r.causation_event_id AS revoked_cause,
 r.upstream_event_id AS revoked_upstream,
 b.event_id AS blocked_event,b.causation_event_id AS blocked_cause,
 b.upstream_event_id AS blocked_upstream
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events i
 ON i.mission_id=t.mission_id
AND i.event_type='AUTHORIZATION_REVOKED'
AND i.upstream_event_id=t.revocation_event_id
JOIN vulndesk.cti_events r
 ON r.mission_id=t.mission_id AND r.task_id=t.task_id
AND r.event_type='TASK_AUTHORIZATION_REVOKED'
AND r.causation_event_id=i.event_id
JOIN vulndesk.cti_events b
 ON b.mission_id=t.mission_id AND b.task_id=t.task_id
AND b.event_type='TASK_DISPATCH_BLOCKED'
AND b.causation_event_id=r.event_id
WHERE t.mission_id=@stage288_revocation_mission_id
ORDER BY t.id,b.id;

-- G3 causal/upstream mismatch. EXPECTED 0.
SELECT t.task_id,t.revocation_event_id,
 i.event_id AS ingress_event,r.event_id AS revoked_event,b.event_id AS blocked_event
FROM vulndesk.cti_task_contracts t
LEFT JOIN vulndesk.cti_events i
 ON i.mission_id=t.mission_id
AND i.event_type='AUTHORIZATION_REVOKED'
AND i.upstream_event_id=t.revocation_event_id
LEFT JOIN vulndesk.cti_events r
 ON r.mission_id=t.mission_id AND r.task_id=t.task_id
AND r.event_type='TASK_AUTHORIZATION_REVOKED'
AND r.causation_event_id=i.event_id
LEFT JOIN vulndesk.cti_events b
 ON b.mission_id=t.mission_id AND b.task_id=t.task_id
AND b.event_type='TASK_DISPATCH_BLOCKED'
AND b.causation_event_id=r.event_id
WHERE t.mission_id=@stage288_revocation_mission_id
 AND t.authorization_mode='REQUIRED'
 AND t.revocation_event_id IS NOT NULL
 AND(
      i.event_id IS NULL OR r.event_id IS NULL OR b.event_id IS NULL
   OR NOT(i.upstream_event_id <=> t.revocation_event_id)
   OR NOT(r.upstream_event_id <=> t.revocation_event_id)
   OR NOT(b.upstream_event_id <=> t.revocation_event_id)
 );

-- G4 positive revocation-correlated DecisionTrace/Audit. EXPECTED >=1.
SELECT
 d.trace_id,d.decision_type,d.task_id,d.policy_decision_id,
 d.upstream_event_id,
 a.audit_id,a.upstream_event_ref,a.downstream_event_ref,
 e.event_type,e.event_id,e.upstream_event_id AS downstream_upstream
FROM vulndesk.cti_decision_traces d
JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
JOIN vulndesk.cti_events e
 ON e.event_id=a.downstream_event_ref
JOIN vulndesk.cti_task_contracts t
 ON t.task_id=d.task_id
WHERE d.mission_id=@stage288_revocation_mission_id
 AND d.decision_type IN('AUTHORIZATION_REVOCATION','DISPATCH_BLOCK')
 AND d.upstream_event_id=t.revocation_event_id
ORDER BY d.id;

-- G5 AUTHORIZATION_REVOCATION upstream mismatch. EXPECTED 0.
SELECT
 d.trace_id,d.task_id,d.upstream_event_id,t.revocation_event_id,
 a.upstream_event_ref,a.downstream_event_ref,
 e.event_id,e.upstream_event_id AS downstream_upstream
FROM vulndesk.cti_decision_traces d
JOIN vulndesk.cti_task_contracts t ON t.task_id=d.task_id
LEFT JOIN vulndesk.cti_audit_log a
 ON a.mission_id=d.mission_id AND a.trace_id=d.trace_id
AND a.event_type LIKE 'orchestration.decision.%'
LEFT JOIN vulndesk.cti_events e
 ON e.event_id=a.downstream_event_ref
WHERE d.mission_id=@stage288_revocation_mission_id
 AND d.decision_type='AUTHORIZATION_REVOCATION'
 AND(
      t.revocation_event_id IS NULL
   OR NOT(d.upstream_event_id <=> t.revocation_event_id)
   OR a.audit_id IS NULL
   OR NOT(a.upstream_event_ref <=> t.revocation_event_id)
   OR e.event_id IS NULL
   OR NOT(e.upstream_event_id <=> t.revocation_event_id)
 );

-- G6 no dispatch after revocation ingress. EXPECTED 0 for pre-dispatch revoke.
SELECT
 t.task_id,i.created_at AS revocation_ingress_at,
 d.event_id AS later_dispatch,d.created_at AS later_dispatch_at
FROM vulndesk.cti_task_contracts t
JOIN vulndesk.cti_events i
 ON i.mission_id=t.mission_id
AND i.event_type='AUTHORIZATION_REVOKED'
AND i.upstream_event_id=t.revocation_event_id
JOIN vulndesk.cti_events d
 ON d.mission_id=t.mission_id AND d.task_id=t.task_id
AND d.event_type='TASK_DISPATCHED'
AND d.created_at>i.created_at
WHERE t.mission_id=@stage288_revocation_mission_id;

-- G7 final revocation state. EXPECTED 0.
SELECT
 task_id,status,revocation_status,revocation_event_id,
 dispatch_authorized_at,dispatch_blocked_at
FROM vulndesk.cti_task_contracts
WHERE mission_id=@stage288_revocation_mission_id
 AND authorization_mode='REQUIRED'
 AND revocation_event_id IS NOT NULL
 AND(
      status<>'BLOCKED_REVOKED'
   OR revocation_status<>'VERIFIED_REVOKED'
   OR dispatch_authorized_at IS NOT NULL
   OR dispatch_blocked_at IS NULL
 );

-- ============================================================================
-- Closure rule
-- Positive: B1,B3,C1,D1,D3,D5,F,G1,G2,G4 contain data.
-- Zero violations: B2,C2,D2,D4,E2,E3,E4,G3,G5,G6,G7.
-- ============================================================================

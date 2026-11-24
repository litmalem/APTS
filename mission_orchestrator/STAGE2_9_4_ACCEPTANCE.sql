/*
Stage 2.9.4 — Cross-Subsystem Governance Correlation Acceptance
MariaDB databases from the supplied baseline:
  vulndesk
  apts_governance

Set @mission_id to a FRESH governed mission used for runtime acceptance.
This SQL proves the persisted identities on both sides. The HTTP acceptance script proves
that VulnDesk performs the correlation through the aptsGSS service boundary rather than
through a cross-database foreign key.
*/

SET @mission_id = 'REPLACE_WITH_FRESH_MISSION_ID';

/* 1. Local TaskContract Governance bindings. */
SELECT
    task_id,
    mission_id,
    status,
    authorization_mode,
    authorization_authority,
    authorization_authority_component,
    policy_decision_id,
    authorization_request_id,
    scope_contract_id,
    scope_version,
    authorization_governance_event_id,
    pre_dispatch_revalidation_id,
    pre_dispatch_governance_event_id,
    revocation_id,
    revocation_event_id,
    revocation_status
FROM vulndesk.cti_task_contracts
WHERE mission_id = @mission_id
ORDER BY id;

/* 2. Authoritative authorization requests and PolicyDecisions. */
SELECT
    r.request_id,
    r.mission_id,
    r.scope_contract_id,
    r.subject_component,
    r.action_class,
    r.action_name,
    r.resource_type,
    r.resource_value,
    r.request_status,
    d.decision_id,
    d.decision,
    d.decision_status,
    d.decision_hash,
    d.scope_version,
    d.policy_set_id,
    d.policy_version
FROM apts_governance.gov_authorization_requests r
LEFT JOIN apts_governance.gov_policy_decisions d
       ON d.request_id = r.request_id
WHERE r.mission_id = @mission_id
ORDER BY r.id, d.id;

/* 3. Authoritative Governance event identities used by Stage 2.8.8/2.9.4. */
SELECT
    event_id,
    event_type,
    mission_id,
    delivery_status,
    attempt_count,
    delivered_at,
    created_at
FROM apts_governance.gov_event_outbox
WHERE mission_id = @mission_id
ORDER BY id;

/* 4. Local gevent-* references that must resolve in aptsGSS. */
SELECT
    x.reference_kind,
    x.task_id,
    x.governance_event_id,
    CASE WHEN g.event_id IS NULL THEN 'MISSING' ELSE 'RESOLVED' END AS authoritative_resolution,
    g.event_type AS authoritative_event_type,
    g.delivery_status
FROM (
    SELECT task_id, 'AUTHORIZATION' AS reference_kind, authorization_governance_event_id AS governance_event_id
      FROM vulndesk.cti_task_contracts
     WHERE mission_id=@mission_id AND authorization_governance_event_id IS NOT NULL
    UNION ALL
    SELECT task_id, 'REVALIDATION', pre_dispatch_governance_event_id
      FROM vulndesk.cti_task_contracts
     WHERE mission_id=@mission_id AND pre_dispatch_governance_event_id IS NOT NULL
    UNION ALL
    SELECT task_id, 'REVOCATION', revocation_event_id
      FROM vulndesk.cti_task_contracts
     WHERE mission_id=@mission_id AND revocation_event_id IS NOT NULL
) x
LEFT JOIN apts_governance.gov_event_outbox g
       ON g.event_id = x.governance_event_id
ORDER BY x.task_id, x.reference_kind;

/* 5. Mission-wide CTI upstream gevent-* references. */
SELECT
    e.event_id AS cti_event_id,
    e.event_type AS cti_event_type,
    e.task_id,
    e.upstream_event_id,
    CASE WHEN g.event_id IS NULL THEN 'MISSING' ELSE 'RESOLVED' END AS authoritative_resolution,
    g.event_type AS governance_event_type,
    g.delivery_status
FROM vulndesk.cti_events e
LEFT JOIN apts_governance.gov_event_outbox g
       ON g.event_id = e.upstream_event_id
WHERE e.mission_id=@mission_id
  AND e.upstream_event_id LIKE 'gevent-%'
ORDER BY e.id;

/* 6. Acceptance summary. */
SELECT
    @mission_id AS mission_id,
    (SELECT COUNT(*) FROM vulndesk.cti_task_contracts WHERE mission_id=@mission_id) AS task_count,
    (SELECT COUNT(*) FROM vulndesk.cti_task_contracts WHERE mission_id=@mission_id AND authorization_mode='REQUIRED') AS governed_task_count,
    (SELECT COUNT(*) FROM apts_governance.gov_authorization_requests WHERE mission_id=@mission_id) AS governance_request_count,
    (SELECT COUNT(*) FROM apts_governance.gov_policy_decisions WHERE mission_id=@mission_id) AS governance_decision_count,
    (SELECT COUNT(*) FROM apts_governance.gov_event_outbox WHERE mission_id=@mission_id) AS governance_event_count,
    (SELECT COUNT(*) FROM apts_governance.gov_audit_log WHERE mission_id=@mission_id) AS governance_audit_count,
    (
      SELECT COUNT(*)
      FROM (
        SELECT authorization_governance_event_id AS gevent
          FROM vulndesk.cti_task_contracts
         WHERE mission_id=@mission_id AND authorization_governance_event_id IS NOT NULL
        UNION ALL
        SELECT pre_dispatch_governance_event_id
          FROM vulndesk.cti_task_contracts
         WHERE mission_id=@mission_id AND pre_dispatch_governance_event_id IS NOT NULL
        UNION ALL
        SELECT revocation_event_id
          FROM vulndesk.cti_task_contracts
         WHERE mission_id=@mission_id AND revocation_event_id IS NOT NULL
      ) refs
      LEFT JOIN apts_governance.gov_event_outbox g ON g.event_id=refs.gevent
      WHERE g.event_id IS NULL
    ) AS unresolved_task_governance_event_refs;

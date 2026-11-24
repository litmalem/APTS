/* Stage 2.9.6 has no schema migration. Validate Governance persistence used by diagnostics/correlation. */
SELECT
    SUM(table_name='gov_scope_contracts') AS gov_scope_contracts,
    SUM(table_name='gov_authorization_requests') AS gov_authorization_requests,
    SUM(table_name='gov_policy_decisions') AS gov_policy_decisions,
    SUM(table_name='gov_event_outbox') AS gov_event_outbox,
    SUM(table_name='gov_audit_log') AS gov_audit_log,
    5 - COUNT(DISTINCT table_name) AS missing_count
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('gov_scope_contracts','gov_authorization_requests','gov_policy_decisions','gov_event_outbox','gov_audit_log');

SELECT delivery_status, COUNT(*) AS event_count
FROM gov_event_outbox
GROUP BY delivery_status
ORDER BY delivery_status;

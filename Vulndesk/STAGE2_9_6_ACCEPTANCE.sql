/* Stage 2.9.6 has no schema migration. This query validates its required VulnDesk evidence tables. */
SELECT
    SUM(table_name='cti_task_contracts') AS cti_task_contracts,
    SUM(table_name='cti_events') AS cti_events,
    SUM(table_name='cti_decision_traces') AS cti_decision_traces,
    SUM(table_name='cti_audit_log') AS cti_audit_log,
    4 - COUNT(DISTINCT table_name) AS missing_count
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('cti_task_contracts','cti_events','cti_decision_traces','cti_audit_log');

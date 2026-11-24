-- VulnDesk CTI execution hardening corrective state repair
-- Version: hybrid-event-driven-2.2-execution-hardening
--
-- Purpose
-- -------
-- Older runtime semantics counted bounded PARTIAL source refreshes as failures.
-- That could increment failure_count and open the circuit breaker even when the
-- source returned HTTP 2xx, total_failed=0, and the sync was intentionally
-- bounded by max_pages.  This script repairs only source-state rows whose last
-- observation proves that exact benign PARTIAL condition.
--
-- This is a data correction, not a schema migration.

SELECT
    source_id,
    status,
    failure_count,
    circuit_state,
    next_retry_at,
    health_score,
    last_attempt_at,
    JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.sync_status')) AS last_sync_status,
    JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.http_status')) AS last_http_status,
    JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.result.total_failed')) AS last_total_failed
FROM cti_source_state
ORDER BY source_id;

UPDATE cti_source_state
SET
    status = 'DEGRADED',
    failure_count = 0,
    circuit_state = 'CLOSED',
    next_retry_at = NULL,
    health_score = 0.90000,
    last_attempt_at = UTC_TIMESTAMP(),
    updated_at = UTC_TIMESTAMP()
WHERE JSON_VALID(last_observation_json)
  AND UPPER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.sync_status')), '')) = 'PARTIAL'
  AND CAST(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.http_status')), '0') AS UNSIGNED)
      BETWEEN 200 AND 299
  AND CAST(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(last_observation_json, '$.result.total_failed')), '0') AS UNSIGNED) = 0;

SELECT
    source_id,
    status,
    failure_count,
    circuit_state,
    next_retry_at,
    health_score,
    last_attempt_at,
    state_version
FROM cti_source_state
ORDER BY source_id;

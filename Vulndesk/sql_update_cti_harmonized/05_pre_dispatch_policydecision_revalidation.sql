-- Stage 2.6 — Pre-dispatch PolicyDecision Revalidation
-- Adds auditable evidence that a TaskContract carrying external authority was
-- revalidated against aptsGSS immediately before dispatch.

ALTER TABLE cti_task_contracts
    ADD COLUMN IF NOT EXISTS pre_dispatch_revalidation_id VARCHAR(120) NULL AFTER authorization_bound_at,
    ADD COLUMN IF NOT EXISTS pre_dispatch_revalidation_status VARCHAR(30) NULL AFTER pre_dispatch_revalidation_id,
    ADD COLUMN IF NOT EXISTS pre_dispatch_reason_codes_json LONGTEXT NULL AFTER pre_dispatch_revalidation_status,
    ADD COLUMN IF NOT EXISTS pre_dispatch_decision_status VARCHAR(30) NULL AFTER pre_dispatch_reason_codes_json,
    ADD COLUMN IF NOT EXISTS pre_dispatch_decision_hash CHAR(64) NULL AFTER pre_dispatch_decision_status,
    ADD COLUMN IF NOT EXISTS pre_dispatch_scope_version BIGINT NULL AFTER pre_dispatch_decision_hash,
    ADD COLUMN IF NOT EXISTS pre_dispatch_policy_version VARCHAR(100) NULL AFTER pre_dispatch_scope_version,
    ADD COLUMN IF NOT EXISTS pre_dispatch_revalidated_at DATETIME NULL AFTER pre_dispatch_policy_version,
    ADD COLUMN IF NOT EXISTS dispatch_authorized_at DATETIME NULL AFTER pre_dispatch_revalidated_at,
    ADD COLUMN IF NOT EXISTS dispatch_blocked_at DATETIME NULL AFTER dispatch_authorized_at;

CREATE INDEX IF NOT EXISTS idx_cti_task_pre_dispatch_status
    ON cti_task_contracts (pre_dispatch_revalidation_status, pre_dispatch_revalidated_at);

CREATE INDEX IF NOT EXISTS idx_cti_task_dispatch_blocked
    ON cti_task_contracts (dispatch_blocked_at, status);

-- Evidence query: required external tasks must have VALID revalidation before
-- they are RUNNING/COMPLETED/DEGRADED.
SELECT
    task_id,
    mission_id,
    task_type,
    status,
    authorization_mode,
    policy_decision_id,
    authorization_request_id,
    pre_dispatch_revalidation_id,
    pre_dispatch_revalidation_status,
    pre_dispatch_decision_status,
    pre_dispatch_revalidated_at,
    dispatch_authorized_at,
    dispatch_blocked_at
FROM cti_task_contracts
WHERE authorization_mode = 'REQUIRED'
ORDER BY id DESC
LIMIT 20;

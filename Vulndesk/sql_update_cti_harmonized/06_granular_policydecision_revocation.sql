-- Stage 2.7 — Granular PolicyDecision Revocation ↔ TaskContract Invalidation
-- MariaDB 10.11+ / VulnDesk CTI-A01
-- Non-destructive: adds revocation projection metadata and a durable revocation ledger.

ALTER TABLE cti_task_contracts
    ADD COLUMN IF NOT EXISTS revocation_id varchar(120) DEFAULT NULL AFTER dispatch_blocked_at,
    ADD COLUMN IF NOT EXISTS revocation_event_id varchar(120) DEFAULT NULL AFTER revocation_id,
    ADD COLUMN IF NOT EXISTS revocation_status varchar(80) DEFAULT NULL AFTER revocation_event_id,
    ADD COLUMN IF NOT EXISTS revocation_reason text DEFAULT NULL AFTER revocation_status,
    ADD COLUMN IF NOT EXISTS revoked_by varchar(255) DEFAULT NULL AFTER revocation_reason,
    ADD COLUMN IF NOT EXISTS revocation_decision_status varchar(30) DEFAULT NULL AFTER revoked_by,
    ADD COLUMN IF NOT EXISTS revocation_decision_hash char(64) DEFAULT NULL AFTER revocation_decision_status,
    ADD COLUMN IF NOT EXISTS revoked_at datetime DEFAULT NULL AFTER revocation_decision_hash,
    ADD COLUMN IF NOT EXISTS revocation_received_at datetime DEFAULT NULL AFTER revoked_at,
    ADD COLUMN IF NOT EXISTS revocation_verified_at datetime DEFAULT NULL AFTER revocation_received_at;

CREATE INDEX IF NOT EXISTS idx_cti_task_revocation_lookup
    ON cti_task_contracts (policy_decision_id, authorization_mode, status);

CREATE INDEX IF NOT EXISTS idx_cti_task_revocation_status
    ON cti_task_contracts (revocation_status, revoked_at);

CREATE TABLE IF NOT EXISTS cti_policy_decision_revocations (
    id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
    revocation_id varchar(120) NOT NULL,
    governance_event_id varchar(120) DEFAULT NULL,
    local_event_id varchar(120) DEFAULT NULL,
    decision_id varchar(100) DEFAULT NULL,
    request_id varchar(100) DEFAULT NULL,
    mission_id varchar(100) NOT NULL,
    decision_hash char(64) DEFAULT NULL,
    decision_status varchar(30) DEFAULT NULL,
    revocation_scope varchar(60) NOT NULL DEFAULT 'POLICY_DECISION',
    reason text DEFAULT NULL,
    revoked_by varchar(255) DEFAULT NULL,
    source_component varchar(120) DEFAULT NULL,
    verification_status varchar(100) NOT NULL,
    verification_error text DEFAULT NULL,
    affected_task_count int(11) NOT NULL DEFAULT 0,
    active_affected_count int(11) NOT NULL DEFAULT 0,
    payload_json longtext DEFAULT NULL,
    revoked_at datetime DEFAULT NULL,
    received_at datetime NOT NULL DEFAULT current_timestamp(),
    verified_at datetime DEFAULT NULL,
    created_at datetime NOT NULL DEFAULT current_timestamp(),
    updated_at datetime DEFAULT NULL ON UPDATE current_timestamp(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_cti_policy_revocation_id (revocation_id),
    UNIQUE KEY uq_cti_policy_revocation_governance_event (governance_event_id),
    KEY idx_cti_policy_revocation_decision (decision_id, mission_id, received_at),
    KEY idx_cti_policy_revocation_verification (verification_status, received_at),
    CONSTRAINT chk_cti_policy_revocation_payload_json
        CHECK (payload_json IS NULL OR json_valid(payload_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Acceptance probes
SELECT
    policy_decision_id,
    COUNT(*) AS bound_tasks,
    SUM(status='BLOCKED_REVOKED') AS blocked_before_dispatch,
    SUM(status='REVOCATION_PENDING_STOP') AS running_stop_requested,
    SUM(status='CANCELLED_REVOKED') AS revoked_results_quarantined,
    SUM(revocation_status IS NOT NULL) AS revocation_annotated
FROM cti_task_contracts
WHERE authorization_mode='REQUIRED'
GROUP BY policy_decision_id
ORDER BY MAX(id) DESC;

SELECT
    revocation_id,
    governance_event_id,
    decision_id,
    mission_id,
    verification_status,
    affected_task_count,
    active_affected_count,
    revoked_at,
    received_at,
    verified_at
FROM cti_policy_decision_revocations
ORDER BY id DESC
LIMIT 50;

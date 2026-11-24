-- Stage 3.6.5 — Mission Outcome Aggregation
-- Durable immutable snapshots of active-Plan task outcome aggregation.

CREATE TABLE IF NOT EXISTS mission_outcome_aggregations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    aggregation_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(180) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    aggregation_status VARCHAR(100) NOT NULL,
    task_count INT UNSIGNED NOT NULL,
    terminal_task_count INT UNSIGNED NOT NULL,
    verified_complete_count INT UNSIGNED NOT NULL,
    failed_count INT UNSIGNED NOT NULL,
    cancelled_count INT UNSIGNED NOT NULL,
    timed_out_count INT UNSIGNED NOT NULL,
    running_count INT UNSIGNED NOT NULL,
    blocked_count INT UNSIGNED NOT NULL,
    pending_count INT UNSIGNED NOT NULL,
    all_tasks_terminal TINYINT(1) NOT NULL,
    all_tasks_verified_complete TINYINT(1) NOT NULL,
    source_snapshot_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state VARCHAR(40) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    aggregated_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    aggregated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_outcome_aggregation_id (aggregation_id),
    UNIQUE KEY uq_mission_outcome_aggregation_idempotency (mission_id, idempotency_key),
    KEY idx_mission_outcome_aggregation_mission (mission_id, plan_version, id),
    CONSTRAINT fk_mission_outcome_aggregation_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_outcome_aggregation_plan
        FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT chk_mission_outcome_aggregation_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

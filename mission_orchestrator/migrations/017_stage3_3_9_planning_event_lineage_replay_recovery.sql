-- Stage 3.3.9 - Planning Event Lineage, Replay & Recovery
-- Applies after Stage 3.3.8 / migration level 16.
-- Adds one immutable durable planning-recovery checkpoint per active Plan version.
-- Replay is read-only and recovery reconstructs from canonical durable artifacts only.
-- PLAN != AUTHORIZATION. TASK != DISPATCH. READINESS != PERMISSION. PLANNER != GOVERNANCE.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_planning_recovery_checkpoints (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    checkpoint_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    checkpoint_version INT UNSIGNED NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(100) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    source_event_count INT UNSIGNED NOT NULL,
    source_event_tip_sha256 CHAR(64) NOT NULL,
    readiness_projection_id VARCHAR(100) NOT NULL,
    readiness_projection_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_planning_recovery_checkpoint_id (checkpoint_id),
    UNIQUE KEY uq_planning_recovery_checkpoint_version (mission_id, checkpoint_version),
    UNIQUE KEY uq_planning_recovery_plan_version (mission_id, plan_version),
    UNIQUE KEY uq_planning_recovery_idempotency (mission_id, idempotency_key),
    KEY idx_planning_recovery_mission (mission_id, checkpoint_version),
    CONSTRAINT fk_planning_recovery_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_planning_recovery_plan_version FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_planning_recovery_readiness FOREIGN KEY (readiness_projection_id) REFERENCES mission_task_readiness_projections(projection_id),
    CONSTRAINT chk_planning_recovery_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES ('canonical-mission-repository', 'apts-mission-repository-v1', 17,
        'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS', NOW(6), NOW(6))
ON DUPLICATE KEY UPDATE schema_version=VALUES(schema_version), migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model), updated_at=NOW(6);

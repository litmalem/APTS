-- Stage 3.3.8 - Task Readiness & Scheduling Projection
-- Applies after Stage 3.3.7 / migration level 15.
-- Adds immutable structural readiness and dependency-wave schedule projections per active Plan version.
-- READINESS != PERMISSION. READY != AUTHORIZED. TASK != DISPATCH.
-- No Governance authorization query, wall-clock scheduling, resource assignment, target-action dispatch, or target actuation.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_task_readiness_projections (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    projection_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(100) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    ready_task_count INT UNSIGNED NOT NULL,
    blocked_task_count INT UNSIGNED NOT NULL,
    task_count INT UNSIGNED NOT NULL,
    wave_count INT UNSIGNED NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_readiness_projection_id (projection_id),
    UNIQUE KEY uq_task_readiness_projection_plan_version (mission_id, plan_version),
    UNIQUE KEY uq_task_readiness_projection_idempotency (mission_id, idempotency_key),
    KEY idx_task_readiness_projection_mission (mission_id, plan_version),
    CONSTRAINT fk_task_readiness_projection_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_readiness_projection_plan_version FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT chk_task_readiness_projection_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES ('canonical-mission-repository', 'apts-mission-repository-v1', 16,
        'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS', NOW(6), NOW(6))
ON DUPLICATE KEY UPDATE schema_version=VALUES(schema_version), migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model), updated_at=NOW(6);

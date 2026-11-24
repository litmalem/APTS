-- Stage 3.3.7 - Plan Versioning, Replanning & Supersession
-- Applies after Stage 3.3.6 / migration level 14.
-- Adds append-only active Plan-version lineage and a mutable CAS head.
-- PLAN != AUTHORIZATION. No Governance authorization is granted or queried.
-- Replanning does not perform readiness scheduling, target-action dispatch, or target actuation.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_plan_versions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    plan_version_record_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    canonical_plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    activation_type VARCHAR(48) NOT NULL,
    predecessor_plan_version_record_id VARCHAR(100) NULL,
    predecessor_plan_version INT UNSIGNED NULL,
    replan_id VARCHAR(160) NULL,
    replan_transition_id VARCHAR(100) NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    candidate_plan_sha256 CHAR(64) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_plan_version_record (plan_version_record_id),
    UNIQUE KEY uq_mission_plan_version_number (mission_id, plan_version),
    UNIQUE KEY uq_mission_plan_version_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_mission_plan_version_replan (mission_id, replan_id),
    KEY idx_mission_plan_versions_mission (mission_id, plan_version),
    CONSTRAINT fk_mission_plan_version_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_plan_version_plan FOREIGN KEY (canonical_plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT chk_mission_plan_version_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_plan_version_heads (
    mission_id VARCHAR(80) NOT NULL,
    active_plan_version_record_id VARCHAR(100) NOT NULL,
    active_plan_version INT UNSIGNED NOT NULL,
    active_plan_sha256 CHAR(64) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (mission_id),
    UNIQUE KEY uq_mission_plan_version_head_record (active_plan_version_record_id),
    CONSTRAINT fk_mission_plan_version_head_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_plan_version_head_record FOREIGN KEY (active_plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES ('canonical-mission-repository', 'apts-mission-repository-v1', 15,
        'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS', NOW(6), NOW(6))
ON DUPLICATE KEY UPDATE schema_version=VALUES(schema_version), migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model), updated_at=NOW(6);

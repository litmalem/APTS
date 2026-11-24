-- Stage 3.3.6 - Plan Validation & Feasibility Gate
-- Applies after Stage 3.3.5 / migration level 13.
-- Local deterministic validation only. No Governance authorization, readiness,
-- scheduling, target-action dispatch, target actuation, or plan activation.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_plan_validations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    plan_validation_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    generated_plan_id VARCHAR(100) NOT NULL,
    generation_version INT UNSIGNED NOT NULL,
    validation_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    status VARCHAR(40) NOT NULL,
    feasible TINYINT(1) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    source_generated_plan_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_plan_validation_id (plan_validation_id),
    UNIQUE KEY uq_mission_plan_validation_generated (generated_plan_id, generation_version),
    UNIQUE KEY uq_mission_plan_validation_idempotency (mission_id, idempotency_key),
    KEY idx_mission_plan_validations_mission (mission_id, validation_version),
    CONSTRAINT fk_mission_plan_validation_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_plan_validation_plan FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT fk_mission_plan_validation_generated FOREIGN KEY (generated_plan_id) REFERENCES mission_generated_plans(generated_plan_id),
    CONSTRAINT chk_mission_plan_validation_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    14,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6), NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

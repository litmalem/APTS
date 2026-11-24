-- Stage 3.4.2 - Task Routing Intent & Candidate Resolution
-- Target: MariaDB/MySQL. Applies after Stage 3.4.1 / repository migration level 18.
--
-- Architectural boundary:
--   * Materializes an immutable routing intent only for a canonical READY planned task.
--   * Candidate resolution is deterministic and local to the Stage-3.4.1 canonical registry.
--   * Candidate matching requires exact required_subsystem + required_capability + task-schema compatibility.
--   * Candidate != eligible. Candidate resolution != route selection. Route selection != authorization.
--   * Routing intent != delegation. No endpoint resolution. No health probe. No resource assignment.
--   * No Governance query, no authorization grant, no delegation, no target-action dispatch, no actuation.
--   * aptsGSS / GOV-PLANE remains the sole Governance/authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_task_routing_intents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    routing_intent_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    readiness_projection_id VARCHAR(100) NOT NULL,
    planned_task_id VARCHAR(100) NOT NULL,
    task_key VARCHAR(160) NOT NULL,
    schema_version VARCHAR(100) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    registry_id VARCHAR(100) NOT NULL,
    registry_version INT UNSIGNED NOT NULL,
    registry_sha256 CHAR(64) NOT NULL,
    resolution_status VARCHAR(64) NOT NULL,
    candidate_count INT UNSIGNED NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_routing_intent_id (routing_intent_id),
    UNIQUE KEY uq_task_routing_intent_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_task_routing_intent_plan_task (mission_id, plan_version, planned_task_id),
    KEY idx_task_routing_intent_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_task_routing_intent_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_routing_intent_plan
        FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_task_routing_intent_readiness
        FOREIGN KEY (readiness_projection_id) REFERENCES mission_task_readiness_projections(projection_id),
    CONSTRAINT chk_task_routing_intent_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    19,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

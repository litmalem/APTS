-- Stage 3.4.3 - Routing Eligibility & Compatibility Gate
-- Target: MariaDB/MySQL. Applies after Stage 3.4.2 / repository migration level 19.
--
-- Architectural boundary:
--   * Evaluates only candidates already materialized by the immutable Stage-3.4.2 routing intent.
--   * Eligibility uses static canonical contracts: Mission required_subsystems, active Plan/readiness,
--     Stage-3.4.2 candidate bindings, and the canonical Stage-3.4.1 subsystem registry.
--   * Eligible candidate != selected route. Eligibility != authorization. Compatibility != runtime availability.
--   * No route ranking/selection, endpoint resolution, health probe, or resource assignment.
--   * No Governance query, authorization grant, delegation, target-action dispatch, execution, or actuation.
--   * aptsGSS / GOV-PLANE remains the sole Governance/authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_task_routing_eligibility_gates (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    eligibility_gate_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    routing_intent_id VARCHAR(100) NOT NULL,
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
    routing_intent_sha256 CHAR(64) NOT NULL,
    gate_result VARCHAR(64) NOT NULL,
    eligibility_status VARCHAR(64) NOT NULL,
    candidate_count INT UNSIGNED NOT NULL,
    eligible_candidate_count INT UNSIGNED NOT NULL,
    ineligible_candidate_count INT UNSIGNED NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_routing_eligibility_gate_id (eligibility_gate_id),
    UNIQUE KEY uq_task_routing_eligibility_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_task_routing_eligibility_intent (mission_id, routing_intent_id),
    UNIQUE KEY uq_task_routing_eligibility_plan_task (mission_id, plan_version, planned_task_id),
    KEY idx_task_routing_eligibility_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_task_routing_eligibility_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_routing_eligibility_intent
        FOREIGN KEY (routing_intent_id) REFERENCES mission_task_routing_intents(routing_intent_id),
    CONSTRAINT fk_task_routing_eligibility_plan
        FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_task_routing_eligibility_readiness
        FOREIGN KEY (readiness_projection_id) REFERENCES mission_task_readiness_projections(projection_id),
    CONSTRAINT chk_task_routing_eligibility_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    20,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

-- Stage 3.4.4 — Deterministic Route Selection & Decision Record
--
-- Boundary invariants:
--   * Only Stage-3.4.3 ELIGIBLE candidates may participate in route ranking/selection.
--   * Ranking/selection is deterministic and local over immutable canonical artifacts.
--   * Selected route = logical subsystem/capability identity only; no runtime endpoint is bound.
--   * Selected route != runtime availability. Selected route != authorization.
--   * Route selection != delegation. Route selection != dispatch. Route selection != execution.
--   * No endpoint resolution, health probe, resource assignment, Governance query, authorization grant,
--     delegation, dispatch, target-action dispatch, or target actuation is performed here.
--   * aptsGSS / GOV-PLANE remains the sole Governance/authorization authority.

CREATE TABLE IF NOT EXISTS mission_task_route_decisions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    route_decision_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    eligibility_gate_id VARCHAR(100) NOT NULL,
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
    eligibility_gate_sha256 CHAR(64) NOT NULL,
    decision_status VARCHAR(64) NOT NULL,
    route_selected TINYINT(1) NOT NULL,
    eligible_candidate_count INT UNSIGNED NOT NULL,
    selected_subsystem VARCHAR(64) NULL,
    selected_capability VARCHAR(160) NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_route_decision_id (route_decision_id),
    UNIQUE KEY uq_task_route_decision_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_task_route_decision_gate (mission_id, eligibility_gate_id),
    UNIQUE KEY uq_task_route_decision_plan_task (mission_id, plan_version, planned_task_id),
    KEY idx_task_route_decision_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_task_route_decision_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_route_decision_gate
        FOREIGN KEY (eligibility_gate_id) REFERENCES mission_task_routing_eligibility_gates(eligibility_gate_id),
    CONSTRAINT fk_task_route_decision_intent
        FOREIGN KEY (routing_intent_id) REFERENCES mission_task_routing_intents(routing_intent_id),
    CONSTRAINT fk_task_route_decision_plan
        FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_task_route_decision_readiness
        FOREIGN KEY (readiness_projection_id) REFERENCES mission_task_readiness_projections(projection_id),
    CONSTRAINT chk_task_route_decision_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    21,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

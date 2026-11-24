-- Stage 3.3.2 - Planner Input Snapshot & Context Binding
-- Target: MariaDB/MySQL. Applies after Stage 3.3.1 / repository migration level 9.
--
-- Architectural boundary:
--   * Adds one immutable APTS-MO01-owned planner-input snapshot for the current
--     canonical Plan identity/version.
--   * Snapshot content is derived from durable local canonical Mission, Plan,
--     PLANNING activation lineage, Scope, Governance-binding, and PIP facts.
--   * No external context refresh, planner invocation, plan synthesis, task
--     decomposition, Governance authorization query, target dispatch, or target
--     actuation is introduced.
--   * SNAPSHOT != AUTHORIZATION; CONTEXT != PERMISSION; PLAN != AUTHORIZATION;
--     TASK != DISPATCH; READINESS != PERMISSION; PLANNER != GOVERNANCE.
--   * aptsGSS / GOV-PLANE remains the sole Governance/authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_planner_input_snapshots (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    snapshot_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_plan_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_planner_input_snapshot_id (snapshot_id),
    UNIQUE KEY uq_mission_planner_input_snapshot_mission (mission_id),
    UNIQUE KEY uq_mission_planner_input_snapshot_plan (plan_id),
    UNIQUE KEY uq_mission_planner_input_snapshot_idempotency (mission_id, idempotency_key),
    KEY idx_mission_planner_input_snapshots_mission (mission_id, snapshot_version),
    CONSTRAINT fk_mission_planner_input_snapshot_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_planner_input_snapshot_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT chk_mission_planner_input_snapshot_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    10,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

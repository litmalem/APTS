-- Stage 3.3.1 - Canonical Plan Contract & Identity
-- Target: MariaDB/MySQL. Applies after Stage 3.2.10 / repository migration level 8.
--
-- Architectural boundary:
--   * Adds one immutable APTS-MO01-owned canonical plan identity per Mission.
--   * The plan is bound to the exact immutable Mission envelope, exact PLANNING
--     state/version, durable Stage-3.2.4 planning-activation lineage, PIP identity,
--     and current local Scope snapshot when present.
--   * Stage 3.3.1 does NOT invoke a planner, materialize/decompose tasks, revise a
--     plan, grant Governance authorization, dispatch target actions, or actuate targets.
--   * PLAN != AUTHORIZATION; TASK != DISPATCH; READINESS != PERMISSION;
--     PLANNER != GOVERNANCE.
--   * aptsGSS / GOV-PLANE remains the sole Governance/authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_plans (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    plan_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_transition_id VARCHAR(100) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_plan_id (plan_id),
    UNIQUE KEY uq_mission_plan_mission (mission_id),
    UNIQUE KEY uq_mission_plan_idempotency (mission_id, idempotency_key),
    KEY idx_mission_plans_mission (mission_id, plan_version),
    CONSTRAINT fk_mission_plan_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_plan_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    9,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

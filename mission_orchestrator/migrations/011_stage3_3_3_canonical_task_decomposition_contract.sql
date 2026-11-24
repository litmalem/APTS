-- Stage 3.3.3 - Canonical Task Decomposition Contract
-- Target: MariaDB/MySQL. Applies after Stage 3.3.2 / repository migration level 10.
--
-- Architectural boundary:
--   * Materializes an immutable structured planned-task set bound to the exact
--     canonical Plan and immutable Stage-3.3.2 planner-input snapshot.
--   * Planner invocation is NOT performed. The task set is explicitly submitted through
--     the Stage-3.3.3 contract surface and canonicalized by APTS-MO01.
--   * Dependency graph is NOT materialized and DAG validation is NOT performed; those
--     belong to Stage 3.3.4.
--   * Does NOT query Governance authorization, dispatch target work, or perform target actuation.
--   * TASK != DISPATCH; PLAN != AUTHORIZATION; READINESS != PERMISSION;
--     PLANNER != GOVERNANCE. aptsGSS / GOV-PLANE remains authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_task_decompositions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    decomposition_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    snapshot_id VARCHAR(100) NOT NULL,
    snapshot_version INT UNSIGNED NOT NULL,
    decomposition_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    task_set_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_plan_sha256 CHAR(64) NOT NULL,
    source_snapshot_sha256 CHAR(64) NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    task_count INT UNSIGNED NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_task_decomposition_id (decomposition_id),
    UNIQUE KEY uq_mission_task_decomposition_mission (mission_id),
    UNIQUE KEY uq_mission_task_decomposition_plan (plan_id),
    UNIQUE KEY uq_mission_task_decomposition_snapshot (snapshot_id),
    UNIQUE KEY uq_mission_task_decomposition_idempotency (mission_id, idempotency_key),
    KEY idx_mission_task_decompositions_mission (mission_id, decomposition_version),
    CONSTRAINT fk_mission_task_decomposition_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_task_decomposition_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT fk_mission_task_decomposition_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES mission_planner_input_snapshots(snapshot_id),
    CONSTRAINT chk_mission_task_decomposition_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_planned_tasks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planned_task_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    decomposition_id VARCHAR(100) NOT NULL,
    decomposition_version INT UNSIGNED NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    snapshot_id VARCHAR(100) NOT NULL,
    snapshot_version INT UNSIGNED NOT NULL,
    task_key VARCHAR(128) NOT NULL,
    task_index INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    required_subsystem VARCHAR(64) NOT NULL,
    required_capability VARCHAR(128) NOT NULL,
    task_status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_planned_task_id (planned_task_id),
    UNIQUE KEY uq_mission_planned_task_key (decomposition_id, task_key),
    UNIQUE KEY uq_mission_planned_task_index (decomposition_id, task_index),
    KEY idx_mission_planned_tasks_mission (mission_id, task_index),
    KEY idx_mission_planned_tasks_plan (plan_id, task_index),
    CONSTRAINT fk_mission_planned_task_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_planned_task_decomposition
        FOREIGN KEY (decomposition_id) REFERENCES mission_task_decompositions(decomposition_id),
    CONSTRAINT fk_mission_planned_task_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT fk_mission_planned_task_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES mission_planner_input_snapshots(snapshot_id),
    CONSTRAINT chk_mission_planned_task_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    11,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

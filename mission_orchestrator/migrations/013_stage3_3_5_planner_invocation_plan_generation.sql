-- Stage 3.3.5 - Planner Invocation & Plan Generation
-- Target: MariaDB/MySQL. Applies after Stage 3.3.4 / repository migration level 12.
--
-- Architectural boundary:
--   * Invokes an APTS-MO01-local deterministic planner over the immutable Stage-3.3.2
--     planner-input snapshot, Stage-3.3.3 task decomposition, and Stage-3.3.4 validated DAG.
--   * Persists planner invocation evidence and one immutable GENERATED_UNVALIDATED
--     candidate plan artifact for the exact canonical Plan version.
--   * Does NOT perform Stage-3.3.6 feasibility validation, Stage-3.3.8 readiness/scheduling,
--     Governance authorization, target-action dispatch, or target actuation.
--   * PLAN != AUTHORIZATION; TASK != DISPATCH; READINESS != PERMISSION;
--     PLANNER != GOVERNANCE. aptsGSS / GOV-PLANE remains authorization authority.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_planner_invocations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planner_invocation_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    snapshot_id VARCHAR(100) NOT NULL,
    snapshot_version INT UNSIGNED NOT NULL,
    decomposition_id VARCHAR(100) NOT NULL,
    decomposition_version INT UNSIGNED NOT NULL,
    graph_id VARCHAR(100) NOT NULL,
    graph_version INT UNSIGNED NOT NULL,
    generation_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    planner_profile VARCHAR(96) NOT NULL,
    planner_engine VARCHAR(128) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    output_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    source_plan_sha256 CHAR(64) NOT NULL,
    source_snapshot_sha256 CHAR(64) NOT NULL,
    source_decomposition_sha256 CHAR(64) NOT NULL,
    source_task_set_sha256 CHAR(64) NOT NULL,
    source_graph_sha256 CHAR(64) NOT NULL,
    source_node_set_sha256 CHAR(64) NOT NULL,
    source_edge_set_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_planner_invocation_id (planner_invocation_id),
    UNIQUE KEY uq_mission_planner_invocation_plan_version (plan_id, plan_version),
    UNIQUE KEY uq_mission_planner_invocation_idempotency (mission_id, idempotency_key),
    KEY idx_mission_planner_invocations_mission (mission_id, generation_version),
    CONSTRAINT fk_mission_planner_invocation_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_planner_invocation_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT fk_mission_planner_invocation_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES mission_planner_input_snapshots(snapshot_id),
    CONSTRAINT fk_mission_planner_invocation_decomposition
        FOREIGN KEY (decomposition_id) REFERENCES mission_task_decompositions(decomposition_id),
    CONSTRAINT fk_mission_planner_invocation_graph
        FOREIGN KEY (graph_id) REFERENCES mission_task_dependency_graphs(graph_id),
    CONSTRAINT chk_mission_planner_invocation_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_generated_plans (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    generated_plan_id VARCHAR(100) NOT NULL,
    planner_invocation_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    generation_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    status VARCHAR(40) NOT NULL,
    planner_profile VARCHAR(96) NOT NULL,
    planner_output_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    task_count INT UNSIGNED NOT NULL,
    dependency_edge_count INT UNSIGNED NOT NULL,
    planning_layer_count INT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_generated_plan_id (generated_plan_id),
    UNIQUE KEY uq_mission_generated_plan_invocation (planner_invocation_id),
    UNIQUE KEY uq_mission_generated_plan_plan_version (plan_id, plan_version),
    KEY idx_mission_generated_plans_mission (mission_id, generation_version),
    CONSTRAINT fk_mission_generated_plan_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_generated_plan_invocation
        FOREIGN KEY (planner_invocation_id) REFERENCES mission_planner_invocations(planner_invocation_id),
    CONSTRAINT fk_mission_generated_plan_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT chk_mission_generated_plan_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    13,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

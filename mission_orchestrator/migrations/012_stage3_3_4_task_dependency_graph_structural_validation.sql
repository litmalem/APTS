-- Stage 3.3.4 - Task Dependency Graph & Structural Validation
-- Target: MariaDB/MySQL. Applies after Stage 3.3.3 / repository migration level 11.
--
-- Architectural boundary:
--   * Materializes one immutable dependency DAG bound to the exact Stage-3.3.3 decomposition.
--   * Persists normalized dependency-edge contracts and structural validation evidence.
--   * Does NOT mutate Stage-3.3.1 Plan, Stage-3.3.2 snapshot, or Stage-3.3.3 planned-task contracts.
--   * Does NOT invoke a planner, compute readiness/scheduling, query Governance authorization,
--     dispatch target work, or perform target actuation.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_task_dependency_graphs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    graph_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    decomposition_id VARCHAR(100) NOT NULL,
    decomposition_version INT UNSIGNED NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    snapshot_id VARCHAR(100) NOT NULL,
    snapshot_version INT UNSIGNED NOT NULL,
    graph_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    node_set_sha256 CHAR(64) NOT NULL,
    edge_set_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_plan_sha256 CHAR(64) NOT NULL,
    source_snapshot_sha256 CHAR(64) NOT NULL,
    source_decomposition_sha256 CHAR(64) NOT NULL,
    source_task_set_sha256 CHAR(64) NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    node_count INT UNSIGNED NOT NULL,
    edge_count INT UNSIGNED NOT NULL,
    validation_status VARCHAR(32) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_task_dependency_graph_id (graph_id),
    UNIQUE KEY uq_mission_task_dependency_graph_mission (mission_id),
    UNIQUE KEY uq_mission_task_dependency_graph_decomposition (decomposition_id),
    UNIQUE KEY uq_mission_task_dependency_graph_idempotency (mission_id, idempotency_key),
    KEY idx_mission_task_dependency_graphs_mission (mission_id, graph_version),
    CONSTRAINT fk_mission_task_dependency_graph_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_task_dependency_graph_decomposition
        FOREIGN KEY (decomposition_id) REFERENCES mission_task_decompositions(decomposition_id),
    CONSTRAINT fk_mission_task_dependency_graph_plan
        FOREIGN KEY (plan_id) REFERENCES mission_plans(plan_id),
    CONSTRAINT fk_mission_task_dependency_graph_snapshot
        FOREIGN KEY (snapshot_id) REFERENCES mission_planner_input_snapshots(snapshot_id),
    CONSTRAINT chk_mission_task_dependency_graph_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_task_dependency_edges (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dependency_edge_id VARCHAR(100) NOT NULL,
    graph_id VARCHAR(100) NOT NULL,
    graph_version INT UNSIGNED NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    decomposition_id VARCHAR(100) NOT NULL,
    decomposition_version INT UNSIGNED NOT NULL,
    plan_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    from_planned_task_id VARCHAR(100) NOT NULL,
    from_task_key VARCHAR(128) NOT NULL,
    to_planned_task_id VARCHAR(100) NOT NULL,
    to_task_key VARCHAR(128) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_task_dependency_edge_id (dependency_edge_id),
    UNIQUE KEY uq_mission_task_dependency_edge_pair (graph_id, from_planned_task_id, to_planned_task_id),
    KEY idx_mission_task_dependency_edges_graph (graph_id, id),
    KEY idx_mission_task_dependency_edges_mission (mission_id, id),
    CONSTRAINT fk_mission_task_dependency_edge_graph
        FOREIGN KEY (graph_id) REFERENCES mission_task_dependency_graphs(graph_id),
    CONSTRAINT fk_mission_task_dependency_edge_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_task_dependency_edge_from_task
        FOREIGN KEY (from_planned_task_id) REFERENCES mission_planned_tasks(planned_task_id),
    CONSTRAINT fk_mission_task_dependency_edge_to_task
        FOREIGN KEY (to_planned_task_id) REFERENCES mission_planned_tasks(planned_task_id),
    CONSTRAINT chk_mission_task_dependency_edge_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    12,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

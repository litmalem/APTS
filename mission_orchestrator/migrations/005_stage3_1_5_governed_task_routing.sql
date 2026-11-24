-- Stage 3.1.5 - Governed Task Routing
-- Target: MariaDB/MySQL. Applies after Stage 3.1.4.
--
-- Architectural boundary:
--   * APTS-MO01 owns the immutable high-level subsystem routing task contract.
--   * The route destination is derived from a Stage-3.1.4 bound subject_component.
--   * Only NOT_REQUIRED_INTERNAL / non-actuating routing capabilities may be used.
--   * This stage can dispatch a subsystem mission, but it cannot dispatch a target action.
--   * Downstream target actions remain subject to aptsGSS authorization/revalidation.
--   * Canonical mission state is not rewritten by read-only routing reconstruction.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_routed_tasks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    destination_subsystem VARCHAR(32) NOT NULL,
    destination_component VARCHAR(128) NOT NULL,
    capability_id VARCHAR(128) NOT NULL,
    task_status VARCHAR(32) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_routed_task_id (task_id),
    UNIQUE KEY uq_mission_routed_task_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_mission_routed_task_subsystem (mission_id, destination_subsystem),
    KEY idx_mission_routed_tasks_mission (mission_id, id),
    CONSTRAINT fk_mission_routed_task_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_routed_task_json CHECK (JSON_VALID(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_task_dispatch_attempts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dispatch_attempt_id VARCHAR(80) NOT NULL,
    task_id VARCHAR(80) NOT NULL,
    attempt_no INT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    recovered_after_response_loss TINYINT(1) NOT NULL DEFAULT 0,
    external_mission_id VARCHAR(100) NULL,
    response_json LONGTEXT NULL,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_task_dispatch_attempt_id (dispatch_attempt_id),
    UNIQUE KEY uq_mission_task_dispatch_attempt_no (task_id, attempt_no),
    KEY idx_mission_task_dispatch_attempts_task (task_id, attempt_no),
    CONSTRAINT fk_mission_task_dispatch_attempt_task
        FOREIGN KEY (task_id) REFERENCES mission_routed_tasks(task_id),
    CONSTRAINT chk_mission_task_dispatch_response_json
        CHECK (response_json IS NULL OR JSON_VALID(response_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

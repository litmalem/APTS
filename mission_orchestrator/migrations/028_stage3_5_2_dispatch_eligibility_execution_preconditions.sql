-- Stage 3.5.2 — Dispatch Eligibility & Execution Preconditions
-- Immutable fail-closed eligibility/precondition evidence only. A PASSED gate means the
-- Stage-3.5.1 dispatch identity may proceed to authoritative pre-dispatch Governance
-- revalidation. It does NOT authorize execution, resolve endpoints, probe health, assign
-- resources, perform network I/O, dispatch an action, or actuate a target.

CREATE TABLE IF NOT EXISTS mission_execution_dispatch_eligibility_gates (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dispatch_eligibility_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    execution_dispatch_id VARCHAR(100) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    planned_task_id VARCHAR(100) NOT NULL,
    task_key VARCHAR(160) NOT NULL,
    task_readiness_projection_id VARCHAR(100) NOT NULL,
    schema_version VARCHAR(180) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    gate_result VARCHAR(80) NOT NULL,
    eligibility_status VARCHAR(160) NOT NULL,
    execution_precondition_status VARCHAR(160) NOT NULL,
    precondition_count INT UNSIGNED NOT NULL,
    satisfied_precondition_count INT UNSIGNED NOT NULL,
    failed_precondition_count INT UNSIGNED NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state VARCHAR(40) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dispatch_eligibility_id (dispatch_eligibility_id),
    UNIQUE KEY uq_dispatch_eligibility_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_dispatch_eligibility_dispatch (mission_id, execution_dispatch_id),
    KEY idx_dispatch_eligibility_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_dispatch_eligibility_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_dispatch_eligibility_dispatch FOREIGN KEY (execution_dispatch_id) REFERENCES mission_execution_dispatch_contracts(execution_dispatch_id),
    CONSTRAINT fk_dispatch_eligibility_plan FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_dispatch_eligibility_task FOREIGN KEY (planned_task_id) REFERENCES mission_planned_tasks(planned_task_id),
    CONSTRAINT fk_dispatch_eligibility_readiness FOREIGN KEY (task_readiness_projection_id) REFERENCES mission_task_readiness_projections(projection_id),
    CONSTRAINT chk_dispatch_eligibility_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

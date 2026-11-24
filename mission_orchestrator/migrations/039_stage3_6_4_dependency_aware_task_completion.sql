-- Stage 3.6.4 — Dependency-Aware Task Completion
-- Commits one immutable canonical task-completion record only after the exact
-- Stage-3.6.3 evidence-binding verification is VERIFIED and every prerequisite
-- task declared by the current active Plan has its own immutable Stage-3.6.4
-- completion record in the same Plan version.
-- This stage does not release downstream dependencies, recalculate readiness,
-- progress the Plan, complete the Mission, query Governance/runtime, redispatch,
-- create another execution attempt, or actuate a target.

CREATE TABLE IF NOT EXISTS mission_task_completion_commits (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    task_completion_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    planned_task_id VARCHAR(100) NOT NULL,
    task_key VARCHAR(160) NOT NULL,
    evidence_binding_verification_id VARCHAR(100) NOT NULL,
    task_outcome_id VARCHAR(100) NOT NULL,
    eligibility_gate_id VARCHAR(100) NOT NULL,
    schema_version VARCHAR(180) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    completion_status VARCHAR(100) NOT NULL,
    task_outcome_accepted TINYINT(1) NOT NULL,
    task_completion_committed TINYINT(1) NOT NULL,
    dependency_status VARCHAR(100) NOT NULL,
    dependency_count INT UNSIGNED NOT NULL,
    completed_dependency_count INT UNSIGNED NOT NULL,
    dependency_binding_sha256 CHAR(64) NOT NULL,
    evidence_binding_verification_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state VARCHAR(40) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    completed_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    committed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_completion_id (task_completion_id),
    UNIQUE KEY uq_task_completion_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_task_completion_evidence_binding (mission_id, evidence_binding_verification_id),
    UNIQUE KEY uq_task_completion_plan_task (mission_id, plan_version, planned_task_id),
    KEY idx_task_completion_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_task_completion_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_completion_plan FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_task_completion_task FOREIGN KEY (planned_task_id) REFERENCES mission_planned_tasks(planned_task_id),
    CONSTRAINT fk_task_completion_evidence_binding FOREIGN KEY (evidence_binding_verification_id) REFERENCES mission_task_evidence_binding_verifications(verification_id),
    CONSTRAINT fk_task_completion_outcome FOREIGN KEY (task_outcome_id) REFERENCES mission_task_outcomes(task_outcome_id),
    CONSTRAINT fk_task_completion_gate FOREIGN KEY (eligibility_gate_id) REFERENCES mission_task_terminality_eligibility_gates(eligibility_gate_id),
    CONSTRAINT chk_task_completion_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

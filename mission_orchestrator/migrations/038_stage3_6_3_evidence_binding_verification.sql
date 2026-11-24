-- Stage 3.6.3 — Evidence Binding Verification
-- Verifies deterministic local immutable reference/hash bindings across the
-- Stage-3.5.7 execution result/evidence/artifact capture, Stage-3.6.1 canonical
-- task outcome, and Stage-3.6.2 completion-eligible terminality gate.
-- This stage does not dereference evidence/artifact URIs, recompute external
-- content hashes, attest external content authenticity, accept task outcomes,
-- evaluate acceptance criteria, commit completion, transition task/Mission state,
-- release dependencies, recalculate readiness, progress the Plan, contact
-- Governance/runtime, redispatch, create execution attempts, or actuate targets.

CREATE TABLE IF NOT EXISTS mission_task_evidence_binding_verifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    verification_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    planned_task_id VARCHAR(100) NOT NULL,
    task_key VARCHAR(160) NOT NULL,
    task_outcome_id VARCHAR(100) NOT NULL,
    eligibility_gate_id VARCHAR(100) NOT NULL,
    result_capture_id VARCHAR(100) NOT NULL,
    schema_version VARCHAR(180) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    verification_status VARCHAR(80) NOT NULL,
    evidence_binding_verified TINYINT(1) NOT NULL,
    artifact_binding_verified TINYINT(1) NOT NULL,
    evidence_reference_count INT UNSIGNED NOT NULL,
    artifact_reference_count INT UNSIGNED NOT NULL,
    evidence_manifest_sha256 CHAR(64) NOT NULL,
    artifact_manifest_sha256 CHAR(64) NOT NULL,
    task_outcome_sha256 CHAR(64) NOT NULL,
    eligibility_gate_sha256 CHAR(64) NOT NULL,
    result_capture_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state VARCHAR(40) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    verified_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    verified_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_task_evidence_binding_id (verification_id),
    UNIQUE KEY uq_task_evidence_binding_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_task_evidence_binding_gate (mission_id, eligibility_gate_id),
    UNIQUE KEY uq_task_evidence_binding_outcome (mission_id, task_outcome_id),
    UNIQUE KEY uq_task_evidence_binding_plan_task (mission_id, plan_version, planned_task_id),
    KEY idx_task_evidence_binding_mission (mission_id, plan_version, planned_task_id),
    CONSTRAINT fk_task_evidence_binding_mission FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_task_evidence_binding_plan FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_task_evidence_binding_task FOREIGN KEY (planned_task_id) REFERENCES mission_planned_tasks(planned_task_id),
    CONSTRAINT fk_task_evidence_binding_outcome FOREIGN KEY (task_outcome_id) REFERENCES mission_task_outcomes(task_outcome_id),
    CONSTRAINT fk_task_evidence_binding_gate FOREIGN KEY (eligibility_gate_id) REFERENCES mission_task_terminality_eligibility_gates(eligibility_gate_id),
    CONSTRAINT fk_task_evidence_binding_result FOREIGN KEY (result_capture_id) REFERENCES mission_execution_result_captures(result_capture_id),
    CONSTRAINT chk_task_evidence_binding_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

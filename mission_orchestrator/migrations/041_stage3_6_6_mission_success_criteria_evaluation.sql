-- Stage 3.6.6 — Mission Success-Criteria Satisfaction Evaluation
-- Durable immutable evaluations bound to the canonical Mission success criteria and
-- an authoritative Stage-3.6.5 mission-outcome aggregation.

CREATE TABLE IF NOT EXISTS mission_success_criteria_evaluations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    evaluation_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    plan_version_record_id VARCHAR(100) NOT NULL,
    plan_version INT UNSIGNED NOT NULL,
    aggregation_id VARCHAR(100) NOT NULL,
    schema_version VARCHAR(180) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    evaluation_status VARCHAR(100) NOT NULL,
    overall_result VARCHAR(100) NOT NULL,
    criterion_count INT UNSIGNED NOT NULL,
    satisfied_count INT UNSIGNED NOT NULL,
    not_satisfied_count INT UNSIGNED NOT NULL,
    indeterminate_count INT UNSIGNED NOT NULL,
    success_criteria_sha256 CHAR(64) NOT NULL,
    aggregation_sha256 CHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    source_state VARCHAR(40) NOT NULL,
    source_state_version BIGINT UNSIGNED NOT NULL,
    source_version_sha256 CHAR(64) NOT NULL,
    evaluated_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    evaluated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_success_eval_id (evaluation_id),
    UNIQUE KEY uq_mission_success_eval_idempotency (mission_id, idempotency_key),
    KEY idx_mission_success_eval_mission (mission_id, plan_version, id),
    CONSTRAINT fk_mission_success_eval_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT fk_mission_success_eval_plan
        FOREIGN KEY (plan_version_record_id) REFERENCES mission_plan_versions(plan_version_record_id),
    CONSTRAINT fk_mission_success_eval_aggregation
        FOREIGN KEY (aggregation_id) REFERENCES mission_outcome_aggregations(aggregation_id),
    CONSTRAINT chk_mission_success_eval_json CHECK (json_valid(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

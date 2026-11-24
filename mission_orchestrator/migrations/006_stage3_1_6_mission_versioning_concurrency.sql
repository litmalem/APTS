-- Stage 3.1.6 - Mission Versioning & Concurrency Mode
-- Target: MariaDB/MySQL. Applies after Stage 3.1.5.
--
-- Architectural boundary:
--   * APTS-MO01 remains authoritative only for canonical mission definition/state.
--   * CTI state_version / plan_version are observed, never rewritten here.
--   * aptsGSS policy/scope versions are observed from authoritative bindings/decisions.
--   * Cross-resource mutations may use the command gate and a hashed version vector.
--   * Stale command writes are rejected fail-closed; identical command replays are idempotent.
--   * This migration does not enable target-action dispatch or target actuation.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_command_journal (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    command_id VARCHAR(128) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    operation VARCHAR(64) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    expected_version_sha256 CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    before_version_json LONGTEXT NULL,
    after_version_json LONGTEXT NULL,
    result_json LONGTEXT NULL,
    last_error TEXT NULL,
    submitted_by VARCHAR(128) NOT NULL,
    metadata_json LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_command_id (command_id),
    UNIQUE KEY uq_mission_command_idempotency (mission_id, idempotency_key),
    KEY idx_mission_command_journal_mission (mission_id, id),
    CONSTRAINT fk_mission_command_journal_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_command_before_json
        CHECK (before_version_json IS NULL OR JSON_VALID(before_version_json)),
    CONSTRAINT chk_mission_command_after_json
        CHECK (after_version_json IS NULL OR JSON_VALID(after_version_json)),
    CONSTRAINT chk_mission_command_result_json
        CHECK (result_json IS NULL OR JSON_VALID(result_json)),
    CONSTRAINT chk_mission_command_metadata_json
        CHECK (JSON_VALID(metadata_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

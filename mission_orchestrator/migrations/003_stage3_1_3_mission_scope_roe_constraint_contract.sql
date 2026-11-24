-- Stage 3.1.3 - Mission Scope, Rules of Engagement & Constraint Contract
-- Target: MariaDB/MySQL. Applies after Stage 3.1.2.
--
-- Architectural boundary:
--   * APTS-MO01 owns the canonical mission-level definition/snapshot.
--   * aptsGSS remains authoritative for policy evaluation, approval, revocation,
--     emergency stop, and execution authorization.
--   * No Stage-3.1.1 mission envelope row is mutated by this migration.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_scope_contract_heads (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mission_id VARCHAR(80) NOT NULL,
    mission_scope_contract_id VARCHAR(80) NOT NULL,
    current_version BIGINT UNSIGNED NOT NULL,
    current_snapshot_id VARCHAR(80) NOT NULL,
    current_sha256 CHAR(64) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_scope_head_mission (mission_id),
    UNIQUE KEY uq_mission_scope_head_contract (mission_scope_contract_id),
    CONSTRAINT fk_mission_scope_head_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_scope_contract_versions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    mission_scope_contract_id VARCHAR(80) NOT NULL,
    contract_version BIGINT UNSIGNED NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_scope_snapshot (snapshot_id),
    UNIQUE KEY uq_mission_scope_version (mission_id, contract_version),
    UNIQUE KEY uq_mission_scope_idempotency (mission_id, idempotency_key),
    KEY idx_mission_scope_contract_version (mission_scope_contract_id, contract_version),
    CONSTRAINT fk_mission_scope_version_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_scope_contract_json CHECK (JSON_VALID(canonical_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

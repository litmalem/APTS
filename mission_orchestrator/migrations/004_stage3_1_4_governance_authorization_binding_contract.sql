-- Stage 3.1.4 - Governance & Authorization Binding Contract
-- Target: MariaDB/MySQL. Applies after Stage 3.1.3.
--
-- Architectural boundary:
--   * APTS-MO01 persists immutable local bindings between the canonical mission
--     scope snapshot/capabilities and authoritative aptsGSS artifacts.
--   * aptsGSS / GOV-PLANE remains the only policy/authorization authority.
--   * PolicyDecision provenance is recorded locally; it does not grant dispatch.
--   * Pre-dispatch revalidation remains mandatory and is implemented by a later stage.
--   * This migration does not mutate Stage 3.1.1 mission envelopes, Stage 3.1.2
--     mission state, or Stage 3.1.3 scope/RoE snapshots.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_governance_binding_heads (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mission_id VARCHAR(80) NOT NULL,
    mission_governance_binding_id VARCHAR(80) NOT NULL,
    current_version BIGINT UNSIGNED NOT NULL,
    current_binding_snapshot_id VARCHAR(80) NOT NULL,
    current_scope_snapshot_id VARCHAR(80) NOT NULL,
    current_governance_scope_contract_id VARCHAR(100) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_governance_head_mission (mission_id),
    UNIQUE KEY uq_mission_governance_head_binding (mission_governance_binding_id),
    CONSTRAINT fk_mission_governance_head_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_governance_binding_versions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    binding_snapshot_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    mission_governance_binding_id VARCHAR(80) NOT NULL,
    binding_version BIGINT UNSIGNED NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    mission_scope_snapshot_id VARCHAR(80) NOT NULL,
    mission_scope_sha256 CHAR(64) NOT NULL,
    governance_scope_contract_id VARCHAR(100) NOT NULL,
    governance_scope_version INT UNSIGNED NOT NULL,
    governance_scope_contract_hash CHAR(64) NOT NULL,
    policy_set_id VARCHAR(100) NOT NULL,
    external_response_json LONGTEXT NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_governance_binding_snapshot (binding_snapshot_id),
    UNIQUE KEY uq_mission_governance_binding_version (mission_id, binding_version),
    UNIQUE KEY uq_mission_governance_binding_idempotency (mission_id, idempotency_key),
    KEY idx_mission_governance_binding_versions (mission_governance_binding_id, binding_version),
    CONSTRAINT fk_mission_governance_binding_version_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_governance_binding_json CHECK (JSON_VALID(canonical_json)),
    CONSTRAINT chk_mission_governance_external_json CHECK (JSON_VALID(external_response_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Durable operation journal for cross-service idempotency/recovery.  The operation
-- id is projected into aptsGSS scope metadata so a retry can recover an external
-- commit after a lost HTTP response rather than creating a duplicate scope.
CREATE TABLE IF NOT EXISTS mission_governance_binding_operations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    operation_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    expected_binding_version BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    governance_scope_contract_id VARCHAR(100) NULL,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_governance_operation_id (operation_id),
    UNIQUE KEY uq_mission_governance_operation_idempotency (mission_id, idempotency_key),
    CONSTRAINT fk_mission_governance_operation_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Durable authorization operation journal.  The operation id is placed in the
-- authoritative request context and can be resolved from the Governance
-- correlation projection after response loss.
CREATE TABLE IF NOT EXISTS mission_authorization_operations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    operation_id VARCHAR(80) NOT NULL,
    authorization_binding_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    governance_binding_version BIGINT UNSIGNED NOT NULL,
    capability_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    governance_request_id VARCHAR(100) NULL,
    policy_decision_id VARCHAR(100) NULL,
    last_error TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_authorization_operation_id (operation_id),
    UNIQUE KEY uq_mission_authorization_operation_binding (authorization_binding_id),
    UNIQUE KEY uq_mission_authorization_operation_idempotency (mission_id, idempotency_key),
    CONSTRAINT fk_mission_authorization_operation_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_authorization_bindings (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    authorization_binding_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    mission_governance_binding_id VARCHAR(80) NOT NULL,
    governance_binding_version BIGINT UNSIGNED NOT NULL,
    capability_id VARCHAR(128) NOT NULL,
    action_fingerprint CHAR(64) NOT NULL,
    governance_request_id VARCHAR(100) NOT NULL,
    policy_decision_id VARCHAR(100) NOT NULL,
    policy_decision_hash CHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    policy_set_id VARCHAR(100) NOT NULL,
    policy_version INT UNSIGNED NOT NULL,
    scope_contract_id VARCHAR(100) NOT NULL,
    scope_version INT UNSIGNED NOT NULL,
    valid_until DATETIME(6) NOT NULL,
    external_response_json LONGTEXT NOT NULL,
    created_by VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_authorization_binding_id (authorization_binding_id),
    UNIQUE KEY uq_mission_authorization_idempotency (mission_id, idempotency_key),
    UNIQUE KEY uq_mission_authorization_policy_decision (policy_decision_id),
    KEY idx_mission_authorization_bindings_mission (mission_id, id),
    CONSTRAINT fk_mission_authorization_binding_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_authorization_binding_json CHECK (JSON_VALID(canonical_json)),
    CONSTRAINT chk_mission_authorization_external_json CHECK (JSON_VALID(external_response_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

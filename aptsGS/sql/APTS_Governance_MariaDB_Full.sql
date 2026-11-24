-- ============================================================================
-- APTS Governance & Safety Service
-- MariaDB schema - independent non-agent Governance Plane
-- Architecture version: 2026-08-governance-v1
-- ============================================================================

CREATE DATABASE IF NOT EXISTS apts_governance
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE apts_governance;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS gov_policy_sets (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    policy_set_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    status ENUM('DRAFT','ACTIVE','RETIRED') NOT NULL DEFAULT 'DRAFT',
    default_effect ENUM('DENY','REVIEW') NOT NULL DEFAULT 'DENY',
    effective_from DATETIME NULL,
    effective_until DATETIME NULL,
    description TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_policy_sets_id (policy_set_id),
    KEY idx_gov_policy_sets_status (status, version)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_policy_rules (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    rule_id VARCHAR(100) NOT NULL,
    policy_set_id VARCHAR(100) NOT NULL,
    priority INT NOT NULL DEFAULT 100,
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(100) NOT NULL,
    effect ENUM('ALLOW','DENY','REVIEW') NOT NULL,
    action_class VARCHAR(100) NULL,
    condition_json LONGTEXT NULL,
    obligations_json LONGTEXT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_policy_rule_id (rule_id),
    KEY idx_gov_policy_rules_set_priority (policy_set_id, enabled, priority),
    CONSTRAINT fk_gov_policy_rules_set
      FOREIGN KEY (policy_set_id) REFERENCES gov_policy_sets(policy_set_id)
      ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_gov_policy_rules_condition_json
      CHECK (condition_json IS NULL OR JSON_VALID(condition_json)),
    CONSTRAINT chk_gov_policy_rules_obligations_json
      CHECK (obligations_json IS NULL OR JSON_VALID(obligations_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_scope_contracts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    scope_contract_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    status ENUM('DRAFT','ACTIVE','SUSPENDED','EXPIRED','REVOKED') NOT NULL DEFAULT 'DRAFT',
    policy_set_id VARCHAR(100) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    valid_from DATETIME NULL,
    valid_until DATETIME NULL,
    created_by VARCHAR(255) NOT NULL,
    approved_by VARCHAR(255) NULL,
    approved_at DATETIME NULL,
    metadata_json LONGTEXT NULL,
    contract_hash CHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_scope_contract_id (scope_contract_id),
    KEY idx_gov_scope_contract_mission (mission_id, status, version),
    KEY idx_gov_scope_contract_validity (status, valid_from, valid_until),
    CONSTRAINT fk_gov_scope_contract_policy
      FOREIGN KEY (policy_set_id) REFERENCES gov_policy_sets(policy_set_id)
      ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_gov_scope_metadata_json
      CHECK (metadata_json IS NULL OR JSON_VALID(metadata_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_scope_targets (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    scope_target_id VARCHAR(100) NOT NULL,
    scope_contract_id VARCHAR(100) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_value VARCHAR(1000) NOT NULL,
    normalized_value VARCHAR(1000) NULL,
    environment VARCHAR(50) NOT NULL DEFAULT 'LAB',
    allowed TINYINT(1) NOT NULL DEFAULT 1,
    notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_scope_target_id (scope_target_id),
    KEY idx_gov_scope_target_contract (scope_contract_id, allowed),
    KEY idx_gov_scope_target_value (normalized_value(191)),
    CONSTRAINT fk_gov_scope_target_contract
      FOREIGN KEY (scope_contract_id) REFERENCES gov_scope_contracts(scope_contract_id)
      ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_scope_sources (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    scope_source_id VARCHAR(100) NOT NULL,
    scope_contract_id VARCHAR(100) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    source_type VARCHAR(100) NOT NULL DEFAULT 'CTI',
    allowed TINYINT(1) NOT NULL DEFAULT 1,
    constraints_json LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_scope_source_id (scope_source_id),
    KEY idx_gov_scope_source_contract (scope_contract_id, allowed),
    KEY idx_gov_scope_source_source (source_id),
    CONSTRAINT fk_gov_scope_source_contract
      FOREIGN KEY (scope_contract_id) REFERENCES gov_scope_contracts(scope_contract_id)
      ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_gov_scope_source_constraints_json
      CHECK (constraints_json IS NULL OR JSON_VALID(constraints_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_scope_action_constraints (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    constraint_id VARCHAR(100) NOT NULL,
    scope_contract_id VARCHAR(100) NOT NULL,
    action_class VARCHAR(100) NOT NULL,
    action_name VARCHAR(255) NOT NULL DEFAULT '*',
    effect ENUM('ALLOW','DENY','REVIEW') NOT NULL DEFAULT 'DENY',
    max_risk_level ENUM('LOW','MODERATE','HIGH','CRITICAL') NOT NULL DEFAULT 'LOW',
    requires_approval TINYINT(1) NOT NULL DEFAULT 0,
    constraints_json LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_action_constraint_id (constraint_id),
    KEY idx_gov_action_constraint_lookup
      (scope_contract_id, action_class, action_name, effect),
    CONSTRAINT fk_gov_action_constraint_contract
      FOREIGN KEY (scope_contract_id) REFERENCES gov_scope_contracts(scope_contract_id)
      ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_gov_action_constraint_json
      CHECK (constraints_json IS NULL OR JSON_VALID(constraints_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_authorization_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NOT NULL,
    scope_contract_id VARCHAR(100) NULL,
    subject_component VARCHAR(255) NOT NULL,
    action_class VARCHAR(100) NOT NULL,
    action_name VARCHAR(255) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_value VARCHAR(1000) NOT NULL,
    context_json LONGTEXT NULL,
    evidence_refs_json LONGTEXT NULL,
    requested_by VARCHAR(255) NULL,
    request_status ENUM('EVALUATING','ALLOW','DENY','REVIEW','CANCELLED') NOT NULL DEFAULT 'EVALUATING',
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_authorization_request_id (request_id),
    KEY idx_gov_authorization_mission (mission_id, request_status, requested_at),
    KEY idx_gov_authorization_scope (scope_contract_id),
    CONSTRAINT fk_gov_authorization_scope
      FOREIGN KEY (scope_contract_id) REFERENCES gov_scope_contracts(scope_contract_id)
      ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_gov_authorization_context_json
      CHECK (context_json IS NULL OR JSON_VALID(context_json)),
    CONSTRAINT chk_gov_authorization_evidence_json
      CHECK (evidence_refs_json IS NULL OR JSON_VALID(evidence_refs_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_risk_assessments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    assessment_id VARCHAR(100) NOT NULL,
    request_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NOT NULL,
    risk_score DECIMAL(6,2) NOT NULL,
    risk_level ENUM('LOW','MODERATE','HIGH','CRITICAL') NOT NULL,
    factors_json LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_risk_assessment_id (assessment_id),
    KEY idx_gov_risk_request (request_id),
    KEY idx_gov_risk_mission (mission_id, risk_level, created_at),
    CONSTRAINT fk_gov_risk_request
      FOREIGN KEY (request_id) REFERENCES gov_authorization_requests(request_id)
      ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT chk_gov_risk_factors_json CHECK (JSON_VALID(factors_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_approval_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    approval_request_id VARCHAR(100) NOT NULL,
    authorization_request_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NOT NULL,
    risk_level ENUM('LOW','MODERATE','HIGH','CRITICAL') NOT NULL,
    reason TEXT NOT NULL,
    required_approver_role VARCHAR(100) NOT NULL DEFAULT 'SECURITY_APPROVER',
    status ENUM('PENDING','APPROVED','DENIED','EXPIRED','CANCELLED') NOT NULL DEFAULT 'PENDING',
    expires_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_approval_request_id (approval_request_id),
    KEY idx_gov_approval_mission (mission_id, status, expires_at),
    KEY idx_gov_approval_authorization (authorization_request_id),
    CONSTRAINT fk_gov_approval_authorization
      FOREIGN KEY (authorization_request_id) REFERENCES gov_authorization_requests(request_id)
      ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_approval_decisions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    approval_decision_id VARCHAR(100) NOT NULL,
    approval_request_id VARCHAR(100) NOT NULL,
    approver_id VARCHAR(255) NOT NULL,
    approver_role VARCHAR(100) NOT NULL,
    decision ENUM('APPROVE','DENY') NOT NULL,
    reason TEXT NOT NULL,
    decision_hash CHAR(64) NOT NULL,
    decided_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_approval_decision_id (approval_decision_id),
    KEY idx_gov_approval_decision_request (approval_request_id, decided_at),
    CONSTRAINT fk_gov_approval_decision_request
      FOREIGN KEY (approval_request_id) REFERENCES gov_approval_requests(approval_request_id)
      ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_policy_decisions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    decision_id VARCHAR(100) NOT NULL,
    request_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NOT NULL,
    policy_set_id VARCHAR(100) NULL,
    policy_version INT NULL,
    scope_contract_id VARCHAR(100) NULL,
    scope_version INT NULL,
    decision ENUM('ALLOW','DENY','REVIEW') NOT NULL,
    reason_codes_json LONGTEXT NOT NULL,
    constraints_json LONGTEXT NULL,
    requires_human_approval TINYINT(1) NOT NULL DEFAULT 0,
    approval_request_id VARCHAR(100) NULL,
    valid_from DATETIME NOT NULL,
    valid_until DATETIME NOT NULL,
    decision_hash CHAR(64) NOT NULL,
    supersedes_decision_id VARCHAR(100) NULL,
    decision_status ENUM('ACTIVE','REVOKED','EXPIRED','SUPERSEDED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_policy_decision_id (decision_id),
    KEY idx_gov_policy_decision_request (request_id, created_at),
    KEY idx_gov_policy_decision_mission (mission_id, decision_status, valid_until),
    KEY idx_gov_policy_decision_scope (scope_contract_id, decision_status),
    CONSTRAINT fk_gov_policy_decision_request
      FOREIGN KEY (request_id) REFERENCES gov_authorization_requests(request_id)
      ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_gov_policy_decision_scope
      FOREIGN KEY (scope_contract_id) REFERENCES gov_scope_contracts(scope_contract_id)
      ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_gov_policy_decision_approval
      FOREIGN KEY (approval_request_id) REFERENCES gov_approval_requests(approval_request_id)
      ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_gov_policy_decision_reasons_json CHECK (JSON_VALID(reason_codes_json)),
    CONSTRAINT chk_gov_policy_decision_constraints_json
      CHECK (constraints_json IS NULL OR JSON_VALID(constraints_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_compliance_obligations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    obligation_id VARCHAR(100) NOT NULL,
    policy_set_id VARCHAR(100) NOT NULL,
    action_class VARCHAR(100) NULL,
    obligation_type VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    mandatory TINYINT(1) NOT NULL DEFAULT 1,
    config_json LONGTEXT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_compliance_obligation_id (obligation_id),
    KEY idx_gov_compliance_policy (policy_set_id, enabled, action_class),
    CONSTRAINT fk_gov_compliance_policy
      FOREIGN KEY (policy_set_id) REFERENCES gov_policy_sets(policy_set_id)
      ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_gov_compliance_config_json
      CHECK (config_json IS NULL OR JSON_VALID(config_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_emergency_state (
    singleton_id TINYINT UNSIGNED NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 0,
    reason TEXT NULL,
    version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    activated_by VARCHAR(255) NULL,
    activated_at DATETIME NULL,
    released_by VARCHAR(255) NULL,
    released_at DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (singleton_id),
    CONSTRAINT chk_gov_emergency_singleton CHECK (singleton_id = 1)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_emergency_actions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    action_id VARCHAR(100) NOT NULL,
    action_type ENUM('ACTIVATE','RELEASE') NOT NULL,
    actor_id VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    metadata_json LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_emergency_action_id (action_id),
    KEY idx_gov_emergency_action_created (created_at),
    CONSTRAINT chk_gov_emergency_action_metadata_json
      CHECK (metadata_json IS NULL OR JSON_VALID(metadata_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_audit_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    audit_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    actor_id VARCHAR(255) NULL,
    mission_id VARCHAR(100) NULL,
    subject_type VARCHAR(100) NULL,
    subject_id VARCHAR(255) NULL,
    payload_json LONGTEXT NULL,
    previous_hash CHAR(64) NULL,
    record_hash CHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_audit_id (audit_id),
    KEY idx_gov_audit_mission (mission_id, created_at),
    KEY idx_gov_audit_subject (subject_type, subject_id, created_at),
    KEY idx_gov_audit_event (event_type, created_at),
    CONSTRAINT chk_gov_audit_payload_json
      CHECK (payload_json IS NULL OR JSON_VALID(payload_json))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gov_event_outbox (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(100) NULL,
    event_type VARCHAR(100) NOT NULL,
    source_component VARCHAR(100) NOT NULL DEFAULT 'GOV-PLANE',
    severity VARCHAR(20) NOT NULL DEFAULT 'INFO',
    payload_json LONGTEXT NOT NULL,
    delivery_status ENUM('PENDING','DELIVERED','FAILED') NOT NULL DEFAULT 'PENDING',
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    next_attempt_at DATETIME NULL,
    delivered_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_gov_event_outbox_event (event_id),
    KEY idx_gov_event_outbox_delivery (delivery_status, next_attempt_at, id),
    KEY idx_gov_event_outbox_mission (mission_id, event_type, created_at),
    CONSTRAINT chk_gov_event_outbox_payload_json CHECK (JSON_VALID(payload_json))
) ENGINE=InnoDB;

-- Bootstrap the singleton emergency-state row. A missing row is treated as fail-safe active by code.
INSERT INTO gov_emergency_state
    (singleton_id, active, reason, version, updated_at)
VALUES
    (1, 0, 'INITIALIZED', 1, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE singleton_id=VALUES(singleton_id);

SET FOREIGN_KEY_CHECKS = 1;
-- ============================================================================
-- Default APTS Governance policy set
-- Deny-by-default. Scope contracts must explicitly allow action classes.
-- ============================================================================
USE apts_governance;

INSERT INTO gov_policy_sets
    (policy_set_id, name, version, status, default_effect, effective_from, description)
VALUES
    ('default-policy', 'APTS Default Governance Policy', 1, 'ACTIVE', 'DENY',
     CURRENT_TIMESTAMP,
     'Deny-by-default baseline policy for CTI and future Pentest subsystems.')
ON DUPLICATE KEY UPDATE
    name=VALUES(name),
    status='ACTIVE',
    default_effect='DENY',
    description=VALUES(description),
    updated_at=CURRENT_TIMESTAMP;

INSERT INTO gov_policy_rules
    (rule_id, policy_set_id, priority, rule_name, rule_type, effect,
     action_class, condition_json, obligations_json, enabled)
VALUES
    ('GOV-R001', 'default-policy', 1,
     'Emergency stop preempts target actions', 'HARD_GUARD', 'DENY', NULL,
     '{"when":"emergency_stop_active","except":["INTERNAL_REASONING","REPORTING"]}',
     '{"reason_code":"EMERGENCY_STOP_ACTIVE"}', 1),
    ('GOV-R010', 'default-policy', 10,
     'Destructive actions are forbidden', 'HARD_GUARD', 'DENY', 'DESTRUCTIVE_ACTION',
     '{"always":true}',
     '{"reason_code":"HARD_DENY_DESTRUCTIVE_ACTION"}', 1),
    ('GOV-R020', 'default-policy', 20,
     'Unknown actions are deny-by-default', 'DEFAULT', 'DENY', NULL,
     '{"unknown_action":true}',
     '{"reason_code":"UNKNOWN_ACTION_DENIED"}', 1),
    ('GOV-R100', 'default-policy', 100,
     'Internal reasoning has no target actuation authority', 'BOUNDARY', 'ALLOW', 'INTERNAL_REASONING',
     '{"target_actuation":false}',
     '{"constraints":{"target_actuation":false}}', 1),
    ('GOV-R110', 'default-policy', 110,
     'Reporting has no target actuation authority', 'BOUNDARY', 'ALLOW', 'REPORTING',
     '{"target_actuation":false}',
     '{"constraints":{"target_actuation":false}}', 1),
    ('GOV-R200', 'default-policy', 200,
     'CTI source reads require source allowlist', 'SCOPE_GUARD', 'ALLOW', 'CTI_SOURCE_READ',
     '{"requires_source_allowlist":true}',
     '{"reason_code":"SOURCE_ALLOWLIST_REQUIRED"}', 1)
ON DUPLICATE KEY UPDATE
    priority=VALUES(priority),
    rule_name=VALUES(rule_name),
    rule_type=VALUES(rule_type),
    effect=VALUES(effect),
    action_class=VALUES(action_class),
    condition_json=VALUES(condition_json),
    obligations_json=VALUES(obligations_json),
    enabled=VALUES(enabled),
    updated_at=CURRENT_TIMESTAMP;

INSERT INTO gov_compliance_obligations
    (obligation_id, policy_set_id, action_class, obligation_type, description,
     mandatory, config_json, enabled)
VALUES
    ('GOV-O001', 'default-policy', NULL, 'AUDIT',
     'Every policy decision must be written to the immutable-style chained audit log.',
     1, '{"chain_hash":"sha256"}', 1),
    ('GOV-O002', 'default-policy', 'CTI_SOURCE_READ', 'PROVENANCE',
     'External CTI acquisition must retain source/provenance references in downstream artifacts.',
     1, '{"required":true}', 1),
    ('GOV-O003', 'default-policy', 'CONTROLLED_EXPLOITATION', 'HUMAN_APPROVAL',
     'Controlled exploitation requires an explicit scope action constraint and approval when configured.',
     1, '{"approval_role":"SECURITY_APPROVER"}', 1)
ON DUPLICATE KEY UPDATE
    description=VALUES(description),
    mandatory=VALUES(mandatory),
    config_json=VALUES(config_json),
    enabled=VALUES(enabled),
    updated_at=CURRENT_TIMESTAMP;

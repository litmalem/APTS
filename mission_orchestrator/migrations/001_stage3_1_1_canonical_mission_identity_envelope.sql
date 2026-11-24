-- Stage 3.1.1 - Canonical Mission Identity & Envelope
-- Target: MariaDB/MySQL. The new Global Mission Orchestrator owns this schema.

CREATE DATABASE IF NOT EXISTS apts_mission_orchestrator
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS global_missions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mission_id VARCHAR(80) NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    client_request_id VARCHAR(128) NULL,
    client_mission_ref VARCHAR(128) NULL,
    correlation_id VARCHAR(80) NOT NULL,
    parent_mission_id VARCHAR(80) NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_global_missions_mission_id (mission_id),
    UNIQUE KEY uq_global_missions_idempotency (source_system, idempotency_key),
    KEY idx_global_missions_correlation (correlation_id),
    KEY idx_global_missions_parent (parent_mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_envelopes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    envelope_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    envelope_version INT UNSIGNED NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    canonical_json LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_envelopes_envelope_id (envelope_id),
    UNIQUE KEY uq_mission_envelopes_version (mission_id, envelope_version),
    KEY idx_mission_envelopes_mission (mission_id, envelope_version),
    CONSTRAINT fk_mission_envelopes_global_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Stage 3.1.1 deliberately has no UPDATE/DELETE API. Future mission state is stored
-- separately; canonical identity/envelope records remain append-only artifacts.

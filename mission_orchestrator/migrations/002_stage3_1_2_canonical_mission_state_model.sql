-- Stage 3.1.2 - Canonical Mission State Model
-- Target: MariaDB/MySQL. Applies after Stage 3.1.1.
-- Immutable identity/envelope records remain untouched; mutable lifecycle state
-- is stored separately with optimistic state_version semantics.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_states (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    state VARCHAR(40) NOT NULL,
    state_version BIGINT UNSIGNED NOT NULL,
    terminal TINYINT(1) NOT NULL DEFAULT 0,
    last_transition_id VARCHAR(80) NULL,
    last_reason_code VARCHAR(80) NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_states_mission (mission_id),
    KEY idx_mission_states_state (state, terminal, state_version),
    CONSTRAINT fk_mission_states_global_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mission_state_transitions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    transition_id VARCHAR(80) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    from_state VARCHAR(40) NOT NULL,
    to_state VARCHAR(40) NOT NULL,
    from_state_version BIGINT UNSIGNED NOT NULL,
    to_state_version BIGINT UNSIGNED NOT NULL,
    actor VARCHAR(128) NOT NULL,
    reason_code VARCHAR(80) NOT NULL,
    reason TEXT NULL,
    evidence_refs_json LONGTEXT NOT NULL,
    metadata_json LONGTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_state_transition_id (transition_id),
    UNIQUE KEY uq_mission_state_transition_version (mission_id, to_state_version),
    KEY idx_mission_state_transitions_mission (mission_id, to_state_version),
    CONSTRAINT fk_mission_state_transitions_global_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_state_transition_evidence_json
        CHECK (JSON_VALID(evidence_refs_json)),
    CONSTRAINT chk_mission_state_transition_metadata_json
        CHECK (JSON_VALID(metadata_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Upgrade existing Stage-3.1.1 missions. This creates only the mutable state
-- projection; no Stage-3.1.1 envelope row is changed.
INSERT IGNORE INTO mission_states
    (mission_id, schema_version, state, state_version, terminal,
     last_transition_id, last_reason_code, updated_by, created_at, updated_at)
SELECT
    mission_id,
    'apts-global-mission-state-v1',
    'CREATED',
    1,
    0,
    NULL,
    'MISSION_REGISTERED',
    created_by,
    created_at,
    created_at
FROM global_missions;

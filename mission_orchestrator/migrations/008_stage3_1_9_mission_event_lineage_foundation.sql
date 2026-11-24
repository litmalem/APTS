-- Stage 3.1.9 - Mission Event & Lineage Foundation
-- Target: MariaDB/MySQL. Applies after Stage 3.1.8 / repository migration level 7.
--
-- Architectural boundary:
--   * Adds an APTS-MO01-owned append-only Mission event ledger only.
--   * Historical Stage-3.1.1..3.1.8 rows are NOT synthesized into fake events.
--   * aptsGSS remains authoritative for policy/approval/revocation/emergency-stop.
--   * VulnDesk/CTI remains authoritative for CTI-local state_version/plan_version.
--   * No event delivery bus, planner, target dispatch, or target actuation is introduced.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_id VARCHAR(100) NOT NULL,
    mission_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    trace_id VARCHAR(100) NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    causation_id VARCHAR(160) NOT NULL,
    parent_event_id VARCHAR(100) NULL,
    source_component VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    state_version BIGINT UNSIGNED NULL,
    plan_version VARCHAR(120) NULL,
    policy_version VARCHAR(120) NULL,
    payload_json LONGTEXT NOT NULL,
    previous_event_sha256 CHAR(64) NULL,
    canonical_sha256 CHAR(64) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    recorded_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_mission_event_id (event_id),
    UNIQUE KEY uq_mission_event_causation (mission_id, event_type, causation_id),
    KEY idx_mission_events_mission (mission_id, id),
    KEY idx_mission_events_trace (trace_id, id),
    KEY idx_mission_events_correlation (correlation_id, id),
    KEY idx_mission_events_parent (parent_event_id),
    KEY idx_mission_events_causation (mission_id, causation_id),
    CONSTRAINT fk_mission_events_mission
        FOREIGN KEY (mission_id) REFERENCES global_missions(mission_id),
    CONSTRAINT chk_mission_events_payload_json CHECK (json_valid(payload_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    8,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

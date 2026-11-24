-- Stage 3.1.7 - Mission Persistence & Repository Model
-- Target: MariaDB/MySQL. Applies after Stage 3.1.6.
--
-- Architectural boundary:
--   * The Mission Orchestrator database remains the durable source of truth for
--     canonical global mission artifacts owned by APTS-MO01.
--   * Governance decisions/scope remain authoritative in aptsGSS; persisted
--     Mission Orchestrator rows are immutable bindings/provenance, not policy authority.
--   * CTI state/plan remain authoritative in VulnDesk and are not copied into a new
--     local authority domain by this migration.
--   * Repository metadata describes the durable model/migration level only.
--   * No target-action dispatch or target actuation authority is introduced.

USE apts_mission_orchestrator;

CREATE TABLE IF NOT EXISTS mission_repository_metadata (
    repository_id VARCHAR(80) NOT NULL,
    schema_version VARCHAR(80) NOT NULL,
    migration_level INT UNSIGNED NOT NULL,
    storage_model VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (repository_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mission_repository_metadata
(repository_id, schema_version, migration_level, storage_model, created_at, updated_at)
VALUES (
    'canonical-mission-repository',
    'apts-mission-repository-v1',
    7,
    'NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS',
    NOW(6),
    NOW(6)
)
ON DUPLICATE KEY UPDATE
    schema_version=VALUES(schema_version),
    migration_level=VALUES(migration_level),
    storage_model=VALUES(storage_model),
    updated_at=NOW(6);

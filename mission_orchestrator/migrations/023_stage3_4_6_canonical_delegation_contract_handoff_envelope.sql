-- Stage 3.4.6 — Canonical Delegation Contract & Handoff Envelope
-- Canonical DDL is also embedded in MissionRepository bootstrap for SQLite/MySQL parity.
CREATE TABLE IF NOT EXISTS mission_task_delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delegation_id TEXT NOT NULL UNIQUE,
    handoff_envelope_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    delegation_authorization_id TEXT NOT NULL,
    route_decision_id TEXT NOT NULL,
    plan_version_record_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    planned_task_id TEXT NOT NULL,
    task_key TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    handoff_schema_version TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    delegation_status TEXT NOT NULL,
    selected_subsystem TEXT NOT NULL,
    selected_capability TEXT NOT NULL,
    selected_capability_version INTEGER NOT NULL,
    handoff_envelope_sha256 TEXT NOT NULL,
    canonical_sha256 TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    source_state_version INTEGER NOT NULL,
    source_version_sha256 TEXT NOT NULL,
    delegated_by TEXT NOT NULL,
    reason TEXT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(mission_id, idempotency_key),
    UNIQUE(mission_id, delegation_authorization_id),
    UNIQUE(mission_id, plan_version, planned_task_id)
);
CREATE INDEX IF NOT EXISTS idx_mission_task_delegations_mission
    ON mission_task_delegations(mission_id, plan_version, planned_task_id);

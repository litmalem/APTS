-- Stage 3.4.7 — Delegation Delivery, Acknowledgement & Ownership
-- Append-only control-plane delivery/ACK/ownership receipt. This does not dispatch or authorize execution.
CREATE TABLE IF NOT EXISTS mission_delegation_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_receipt_id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    delegation_id TEXT NOT NULL,
    handoff_envelope_id TEXT NOT NULL,
    plan_version_record_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    planned_task_id TEXT NOT NULL,
    task_key TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    acknowledgement_status TEXT NOT NULL,
    ownership_status TEXT NOT NULL,
    recipient_subsystem TEXT NOT NULL,
    recipient_capability TEXT NOT NULL,
    recipient_capability_version INTEGER NOT NULL,
    delegation_sha256 TEXT NOT NULL,
    handoff_envelope_sha256 TEXT NOT NULL,
    canonical_sha256 TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    source_state_version INTEGER NOT NULL,
    source_version_sha256 TEXT NOT NULL,
    acknowledged_by TEXT NOT NULL,
    ownership_accepted_by TEXT NOT NULL,
    reason TEXT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(mission_id, idempotency_key),
    UNIQUE(mission_id, delegation_id)
);
CREATE INDEX IF NOT EXISTS idx_mission_delegation_deliveries_mission
    ON mission_delegation_deliveries(mission_id, plan_version, planned_task_id);

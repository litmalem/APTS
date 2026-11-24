CREATE TABLE IF NOT EXISTS execution_authorizations (
    authorization_id TEXT PRIMARY KEY,
    revalidation_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    mission_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    pentest_id TEXT NOT NULL,
    envelope_sha256 TEXT NOT NULL CHECK (length(envelope_sha256)=64),
    policy_decision_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW','DENY','REVIEW')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    stored_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_authorizations_execution
    ON execution_authorizations(execution_id,stored_at,authorization_id);
CREATE TRIGGER IF NOT EXISTS execution_authorizations_no_update
BEFORE UPDATE ON execution_authorizations BEGIN
    SELECT RAISE(ABORT,'execution authorizations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_authorizations_no_delete
BEFORE DELETE ON execution_authorizations BEGIN
    SELECT RAISE(ABORT,'execution authorizations are append-only');
END;

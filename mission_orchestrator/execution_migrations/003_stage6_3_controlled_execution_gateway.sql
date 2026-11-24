CREATE TABLE IF NOT EXISTS execution_gateway_submissions (
    gateway_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway_id TEXT NOT NULL UNIQUE,
    submission_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    authorization_id TEXT NOT NULL UNIQUE REFERENCES execution_authorizations(authorization_id),
    mission_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    pentest_id TEXT NOT NULL,
    pentest_task_id TEXT NOT NULL,
    envelope_sha256 TEXT NOT NULL CHECK (length(envelope_sha256)=64),
    status TEXT NOT NULL CHECK (status IN ('ADMITTED_AWAITING_ADAPTER','DENIED','REVIEW_REQUIRED','BLOCKED_CONSTRAINTS','BLOCKED_BUDGET','BLOCKED_DUPLICATE')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    stored_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gateway_one_admission_per_execution
    ON execution_gateway_submissions(execution_id) WHERE status='ADMITTED_AWAITING_ADAPTER';
CREATE INDEX IF NOT EXISTS idx_gateway_execution
    ON execution_gateway_submissions(execution_id,gateway_sequence);
CREATE INDEX IF NOT EXISTS idx_gateway_mission_budget
    ON execution_gateway_submissions(mission_id,status,gateway_sequence);
CREATE INDEX IF NOT EXISTS idx_gateway_pentest_budget
    ON execution_gateway_submissions(pentest_id,status,gateway_sequence);
CREATE INDEX IF NOT EXISTS idx_gateway_task_budget
    ON execution_gateway_submissions(pentest_task_id,status,gateway_sequence);
CREATE TRIGGER IF NOT EXISTS execution_gateway_submissions_no_update
BEFORE UPDATE ON execution_gateway_submissions BEGIN
    SELECT RAISE(ABORT,'execution gateway submissions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_gateway_submissions_no_delete
BEFORE DELETE ON execution_gateway_submissions BEGIN
    SELECT RAISE(ABORT,'execution gateway submissions are append-only');
END;

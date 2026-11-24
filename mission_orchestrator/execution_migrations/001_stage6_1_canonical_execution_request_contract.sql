CREATE TABLE IF NOT EXISTS execution_repository_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    migration_level INTEGER NOT NULL CHECK (migration_level >= 1)
);

CREATE TABLE IF NOT EXISTS execution_requests (
    execution_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    pentest_id TEXT NOT NULL,
    pentest_task_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'AWAITING_AUTHORIZATION'),
    envelope_sha256 TEXT NOT NULL CHECK (length(envelope_sha256) = 64),
    envelope_json TEXT NOT NULL,
    stored_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_requests_mission
    ON execution_requests(mission_id, stored_at, execution_id);
CREATE INDEX IF NOT EXISTS idx_execution_requests_pentest
    ON execution_requests(pentest_id, stored_at, execution_id);
CREATE INDEX IF NOT EXISTS idx_execution_requests_task
    ON execution_requests(task_id, stored_at, execution_id);

CREATE TRIGGER IF NOT EXISTS execution_requests_no_update
BEFORE UPDATE ON execution_requests
BEGIN
    SELECT RAISE(ABORT, 'execution requests are immutable');
END;

CREATE TRIGGER IF NOT EXISTS execution_requests_no_delete
BEFORE DELETE ON execution_requests
BEGIN
    SELECT RAISE(ABORT, 'execution requests are append-only');
END;

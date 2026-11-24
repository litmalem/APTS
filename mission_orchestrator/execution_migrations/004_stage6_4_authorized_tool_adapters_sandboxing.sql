CREATE TABLE IF NOT EXISTS execution_adapter_invocations (
    adapter_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT NOT NULL UNIQUE,
    invocation_request_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    authorization_id TEXT NOT NULL UNIQUE REFERENCES execution_authorizations(authorization_id),
    mission_id TEXT NOT NULL,
    pentest_id TEXT NOT NULL,
    pentest_task_id TEXT NOT NULL,
    gateway_id TEXT REFERENCES execution_gateway_submissions(gateway_id),
    credential_lease_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('RESERVED','BLOCKED')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    reserved_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adapter_one_execution ON execution_adapter_invocations(execution_id) WHERE status='RESERVED';
CREATE UNIQUE INDEX IF NOT EXISTS idx_adapter_one_lease ON execution_adapter_invocations(credential_lease_id) WHERE status='RESERVED' AND credential_lease_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_adapter_one_gateway ON execution_adapter_invocations(gateway_id) WHERE status='RESERVED' AND gateway_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_adapter_mission ON execution_adapter_invocations(mission_id,adapter_sequence);
CREATE TABLE IF NOT EXISTS execution_adapter_results (
    invocation_id TEXT PRIMARY KEY REFERENCES execution_adapter_invocations(invocation_id),
    boundary_authorization_id TEXT UNIQUE REFERENCES execution_authorizations(authorization_id),
    status TEXT NOT NULL CHECK (status IN ('SUCCEEDED','FAILED','TIMEOUT','BLOCKED')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS execution_adapter_invocations_no_update BEFORE UPDATE ON execution_adapter_invocations BEGIN
    SELECT RAISE(ABORT,'adapter claims are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_adapter_invocations_no_delete BEFORE DELETE ON execution_adapter_invocations BEGIN
    SELECT RAISE(ABORT,'adapter claims are append-only');
END;
CREATE TRIGGER IF NOT EXISTS execution_adapter_results_no_update BEFORE UPDATE ON execution_adapter_results BEGIN
    SELECT RAISE(ABORT,'adapter results are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_adapter_results_no_delete BEFORE DELETE ON execution_adapter_results BEGIN
    SELECT RAISE(ABORT,'adapter results are append-only');
END;
CREATE TRIGGER IF NOT EXISTS execution_gateway_submissions_v4_closed BEFORE INSERT ON execution_gateway_submissions
WHEN (SELECT migration_level FROM execution_repository_meta WHERE singleton=1)>=4 BEGIN
    SELECT RAISE(ABORT,'Stage 6.4 requires adapter gateway reservations');
END;

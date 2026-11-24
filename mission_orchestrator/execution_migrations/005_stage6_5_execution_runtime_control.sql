CREATE TABLE IF NOT EXISTS execution_runtime_attempts (
    attempt_id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL UNIQUE REFERENCES execution_adapter_invocations(invocation_id) DEFERRABLE INITIALLY DEFERRED,
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    mission_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 3),
    owner_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    UNIQUE(execution_id,attempt_number)
);
CREATE TABLE IF NOT EXISTS execution_runtime_events (
    event_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES execution_runtime_attempts(attempt_id),
    event_sequence INTEGER NOT NULL CHECK (event_sequence>=1),
    event_type TEXT NOT NULL,
    state_after TEXT NOT NULL CHECK (state_after IN ('AUTHORIZED','DISPATCHED','RUNNING','SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED')),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE(attempt_id,event_sequence)
);
CREATE TABLE IF NOT EXISTS execution_runtime_commands (
    command_id TEXT PRIMARY KEY,
    command_request_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    operation TEXT NOT NULL CHECK (operation IN ('CANCEL','KILL')),
    mission_id TEXT NOT NULL,
    attempt_id TEXT REFERENCES execution_runtime_attempts(attempt_id),
    record_sha256 TEXT NOT NULL CHECK (length(record_sha256)=64),
    record_json TEXT NOT NULL,
    requested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runtime_mission ON execution_runtime_attempts(mission_id,execution_id,attempt_number);
CREATE INDEX IF NOT EXISTS idx_runtime_commands_mission ON execution_runtime_commands(mission_id,operation);
DROP INDEX IF EXISTS idx_adapter_one_execution;
CREATE TRIGGER IF NOT EXISTS execution_adapter_invocations_v5_guard BEFORE INSERT ON execution_adapter_invocations
WHEN (SELECT migration_level FROM execution_repository_meta WHERE singleton=1)>=5 AND NEW.status='RESERVED'
AND NOT EXISTS (SELECT 1 FROM execution_runtime_attempts WHERE invocation_id=NEW.invocation_id) BEGIN
    SELECT RAISE(ABORT,'Stage 6.5 requires a durable runtime attempt');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_attempts_no_update BEFORE UPDATE ON execution_runtime_attempts BEGIN
    SELECT RAISE(ABORT,'runtime attempts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_attempts_no_delete BEFORE DELETE ON execution_runtime_attempts BEGIN
    SELECT RAISE(ABORT,'runtime attempts are append-only');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_events_no_update BEFORE UPDATE ON execution_runtime_events BEGIN
    SELECT RAISE(ABORT,'runtime events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_events_no_delete BEFORE DELETE ON execution_runtime_events BEGIN
    SELECT RAISE(ABORT,'runtime events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_events_terminal BEFORE INSERT ON execution_runtime_events
WHEN EXISTS (SELECT 1 FROM execution_runtime_events WHERE attempt_id=NEW.attempt_id
AND state_after IN ('SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED')) BEGIN
    SELECT RAISE(ABORT,'runtime terminal state is final');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_commands_no_update BEFORE UPDATE ON execution_runtime_commands BEGIN
    SELECT RAISE(ABORT,'runtime commands are immutable');
END;
CREATE TRIGGER IF NOT EXISTS execution_runtime_commands_no_delete BEFORE DELETE ON execution_runtime_commands BEGIN
    SELECT RAISE(ABORT,'runtime commands are append-only');
END;

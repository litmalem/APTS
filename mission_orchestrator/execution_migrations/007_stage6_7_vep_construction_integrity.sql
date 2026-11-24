CREATE TABLE execution_veps (
    vep_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES execution_runtime_attempts(attempt_id),
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    mission_id TEXT NOT NULL,
    pentest_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL UNIQUE REFERENCES execution_evidence_captures(evidence_id),
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    terminal_event_sha256 TEXT NOT NULL CHECK(length(terminal_event_sha256)=64),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL CHECK(length(CAST(record_json AS BLOB))<=2097152),
    constructed_at TEXT NOT NULL
);
CREATE INDEX execution_veps_execution ON execution_veps(execution_id,constructed_at,vep_id);
CREATE TRIGGER execution_veps_no_update BEFORE UPDATE ON execution_veps BEGIN
    SELECT RAISE(ABORT,'VEPs are immutable');
END;
CREATE TRIGGER execution_veps_no_delete BEFORE DELETE ON execution_veps BEGIN
    SELECT RAISE(ABORT,'VEPs are append-only');
END;
CREATE TRIGGER execution_veps_terminal BEFORE INSERT ON execution_veps
WHEN NOT EXISTS (
    SELECT 1 FROM execution_runtime_attempts a
    JOIN execution_requests r ON r.execution_id=a.execution_id
    JOIN execution_evidence_captures c ON c.attempt_id=a.attempt_id
    JOIN execution_runtime_events e ON e.event_id=c.terminal_event_id
    WHERE a.attempt_id=NEW.attempt_id AND a.execution_id=NEW.execution_id
    AND a.mission_id=NEW.mission_id AND r.pentest_id=NEW.pentest_id
    AND c.evidence_id=NEW.evidence_id AND c.record_sha256=NEW.evidence_sha256
    AND e.record_sha256=NEW.terminal_event_sha256
    AND e.state_after IN ('SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED')
) BEGIN
    SELECT RAISE(ABORT,'VEP requires exact terminal evidence and scope');
END;

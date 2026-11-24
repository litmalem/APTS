CREATE TABLE execution_capture_sessions (
    attempt_id TEXT PRIMARY KEY REFERENCES execution_runtime_attempts(attempt_id),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL
);
CREATE TABLE execution_artifacts (
    artifact_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES execution_capture_sessions(attempt_id),
    kind TEXT NOT NULL CHECK(kind IN ('TOOL_IDENTITY','ACTION_PARAMETERS','BEFORE_STATE','STDOUT','STDERR','NETWORK_OBSERVATION','TARGET_RESPONSE','RESULT','AFTER_STATE')),
    payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload)<=131072),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL,
    UNIQUE(attempt_id,kind)
);
CREATE TABLE execution_evidence_captures (
    evidence_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES execution_capture_sessions(attempt_id),
    terminal_event_id TEXT NOT NULL UNIQUE REFERENCES execution_runtime_events(event_id),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL
);
CREATE TRIGGER execution_capture_sessions_no_update BEFORE UPDATE ON execution_capture_sessions BEGIN
    SELECT RAISE(ABORT,'capture sessions are immutable');
END;
CREATE TRIGGER execution_capture_sessions_no_delete BEFORE DELETE ON execution_capture_sessions BEGIN
    SELECT RAISE(ABORT,'capture sessions are append-only');
END;
CREATE TRIGGER execution_artifacts_no_update BEFORE UPDATE ON execution_artifacts BEGIN
    SELECT RAISE(ABORT,'artifacts are immutable');
END;
CREATE TRIGGER execution_artifacts_no_delete BEFORE DELETE ON execution_artifacts BEGIN
    SELECT RAISE(ABORT,'artifacts are append-only');
END;
CREATE TRIGGER execution_artifacts_closed BEFORE INSERT ON execution_artifacts
WHEN EXISTS(SELECT 1 FROM execution_evidence_captures WHERE attempt_id=NEW.attempt_id) BEGIN
    SELECT RAISE(ABORT,'terminal artifact manifest is sealed');
END;
CREATE TRIGGER execution_artifacts_quota BEFORE INSERT ON execution_artifacts
WHEN (SELECT count(*) FROM execution_artifacts WHERE attempt_id=NEW.attempt_id)>=9
OR (SELECT coalesce(sum(length(payload)),0) FROM execution_artifacts WHERE attempt_id=NEW.attempt_id)+length(NEW.payload)>524288 BEGIN
    SELECT RAISE(ABORT,'artifact quota exceeded');
END;
CREATE TRIGGER execution_evidence_captures_no_update BEFORE UPDATE ON execution_evidence_captures BEGIN
    SELECT RAISE(ABORT,'evidence captures are immutable');
END;
CREATE TRIGGER execution_evidence_captures_no_delete BEFORE DELETE ON execution_evidence_captures BEGIN
    SELECT RAISE(ABORT,'evidence captures are append-only');
END;
CREATE TRIGGER execution_evidence_captures_terminal BEFORE INSERT ON execution_evidence_captures
WHEN NOT EXISTS(SELECT 1 FROM execution_runtime_events WHERE event_id=NEW.terminal_event_id
AND attempt_id=NEW.attempt_id AND state_after IN ('SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED')) BEGIN
    SELECT RAISE(ABORT,'evidence requires an exact terminal event');
END;

CREATE TABLE execution_cleanup_receipts (
    attempt_id TEXT PRIMARY KEY REFERENCES execution_runtime_attempts(attempt_id),
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    owner_id TEXT NOT NULL,
    adapter_result_sha256 TEXT NOT NULL CHECK(length(adapter_result_sha256)=64),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL CHECK(json_valid(record_json) AND length(CAST(record_json AS BLOB))<=16384),
    verified_at TEXT NOT NULL
);
CREATE TABLE execution_credential_revocations (
    lease_id TEXT NOT NULL,
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    attempt_id TEXT NOT NULL REFERENCES execution_runtime_attempts(attempt_id),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL CHECK(json_valid(record_json) AND length(CAST(record_json AS BLOB))<=4096),
    revoked_at TEXT NOT NULL,
    PRIMARY KEY(lease_id,execution_id)
);
CREATE TABLE execution_post_action_reports (
    post_action_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES execution_runtime_attempts(attempt_id),
    execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
    vep_id TEXT NOT NULL UNIQUE REFERENCES execution_veps(vep_id),
    vep_sha256 TEXT NOT NULL CHECK(length(vep_sha256)=64),
    terminal_event_sha256 TEXT NOT NULL CHECK(length(terminal_event_sha256)=64),
    state TEXT NOT NULL CHECK(state IN ('CLOSED_LOCAL_RESOURCES','BLOCKED_REQUIRES_REVIEW')),
    record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
    record_json TEXT NOT NULL CHECK(json_valid(record_json) AND length(CAST(record_json AS BLOB))<=65536),
    evaluated_at TEXT NOT NULL
);
CREATE INDEX execution_post_action_execution ON execution_post_action_reports(execution_id,evaluated_at,post_action_id);
CREATE TRIGGER execution_cleanup_receipts_no_update BEFORE UPDATE ON execution_cleanup_receipts BEGIN
    SELECT RAISE(ABORT,'cleanup receipts are immutable');
END;
CREATE TRIGGER execution_cleanup_receipts_no_delete BEFORE DELETE ON execution_cleanup_receipts BEGIN
    SELECT RAISE(ABORT,'cleanup receipts are append-only');
END;
CREATE TRIGGER execution_credential_revocations_no_update BEFORE UPDATE ON execution_credential_revocations BEGIN
    SELECT RAISE(ABORT,'credential revocations are immutable');
END;
CREATE TRIGGER execution_credential_revocations_no_delete BEFORE DELETE ON execution_credential_revocations BEGIN
    SELECT RAISE(ABORT,'credential revocations are append-only');
END;
CREATE TRIGGER execution_post_action_reports_no_update BEFORE UPDATE ON execution_post_action_reports BEGIN
    SELECT RAISE(ABORT,'post-action reports are immutable');
END;
CREATE TRIGGER execution_post_action_reports_no_delete BEFORE DELETE ON execution_post_action_reports BEGIN
    SELECT RAISE(ABORT,'post-action reports are append-only');
END;
CREATE TRIGGER execution_cleanup_receipts_owned BEFORE INSERT ON execution_cleanup_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM execution_runtime_attempts a JOIN execution_runtime_events g ON g.attempt_id=a.attempt_id AND g.event_sequence=1
    WHERE a.attempt_id=NEW.attempt_id AND a.execution_id=NEW.execution_id AND a.owner_id=NEW.owner_id
    AND json_extract(g.record_json,'$.data.cleanup_contract_sha256') IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM execution_runtime_events e WHERE e.attempt_id=a.attempt_id
        AND e.state_after IN ('SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED'))
) BEGIN
    SELECT RAISE(ABORT,'cleanup receipt requires an enrolled active owner; no legacy backfill');
END;
CREATE TRIGGER execution_credential_revocations_scoped BEFORE INSERT ON execution_credential_revocations
WHEN NOT EXISTS (
    SELECT 1 FROM execution_runtime_attempts a JOIN execution_adapter_invocations c ON c.invocation_id=a.invocation_id
    WHERE a.attempt_id=NEW.attempt_id AND a.execution_id=NEW.execution_id
    AND json_extract(c.record_json,'$.controls.credential_lease_id')=NEW.lease_id
) BEGIN
    SELECT RAISE(ABORT,'credential revocation requires exact execution lease scope');
END;
CREATE TRIGGER execution_post_action_reports_terminal BEFORE INSERT ON execution_post_action_reports
WHEN NOT EXISTS (
    SELECT 1 FROM execution_veps v WHERE v.vep_id=NEW.vep_id AND v.attempt_id=NEW.attempt_id
    AND v.execution_id=NEW.execution_id AND v.record_sha256=NEW.vep_sha256
    AND v.terminal_event_sha256=NEW.terminal_event_sha256
) OR (NEW.state='CLOSED_LOCAL_RESOURCES' AND (
    NOT EXISTS (SELECT 1 FROM execution_cleanup_receipts r WHERE r.attempt_id=NEW.attempt_id
        AND json_extract(r.record_json,'$.local_resources_verified')=1)
    OR NOT EXISTS (
        SELECT 1 FROM execution_veps v
        JOIN execution_runtime_events e ON e.record_sha256=v.terminal_event_sha256
        JOIN execution_runtime_attempts a ON a.attempt_id=v.attempt_id
        JOIN execution_adapter_results o ON o.invocation_id=a.invocation_id
        JOIN execution_cleanup_receipts r ON r.attempt_id=a.attempt_id
        WHERE v.vep_id=NEW.vep_id AND e.attempt_id=NEW.attempt_id
        AND json_extract(e.record_json,'$.data.target_io_uncertain')=0
        AND json_extract(e.record_json,'$.data.resources_closed')=1
        AND o.record_sha256=r.adapter_result_sha256
        AND json_extract(o.record_json,'$.credential_lease') IS NULL
    )
    OR EXISTS (
        SELECT 1 FROM execution_runtime_attempts a
        JOIN execution_adapter_invocations c ON c.invocation_id=a.invocation_id
        WHERE a.attempt_id=NEW.attempt_id
        AND json_extract(c.record_json,'$.controls.credential_lease_id') IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM execution_credential_revocations r WHERE r.execution_id=a.execution_id
            AND r.lease_id=json_extract(c.record_json,'$.controls.credential_lease_id'))
    )
    OR json_extract(NEW.record_json,'$.execution_closed') IS NOT 1
    OR json_extract(NEW.record_json,'$.effect_verification.target_io_uncertain') IS NOT 0
    OR json_extract(NEW.record_json,'$.credentials.lease_acquired') IS NOT 0
)) BEGIN
    SELECT RAISE(ABORT,'post-action closure requires exact VEP and verified local resources');
END;

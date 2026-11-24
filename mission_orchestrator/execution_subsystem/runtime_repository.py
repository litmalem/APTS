"""Append-only lifecycle with transactional admission, commands, and finalization."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from .adapter_contract import RESULT_DOMAIN, verify_adapter_result
from .adapter_repository import ExecutionAdapterRepository
from .authorization_contract import parse_time
from .execution_contract import (ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceNotFound, ExecutionSourceRejected,
    canonical_json, require_id, sha256_hex, with_integrity)
from .request_repository import EXECUTION_REPOSITORY_SCHEMA_VERSION, ExecutionRepositoryError
from .runtime_contract import (ATTEMPT_DOMAIN, COMMAND_DOMAIN, EVENT_DOMAIN, MAX_ATTEMPTS,
    RETRY_SCHEMA, RUNTIME_CONTROL_VERSION, TERMINAL, adapter_intake, allowed_transition,
    attempt_id, verify_attempt, verify_command, verify_event)


class ExecutionRuntimeRepository(ExecutionAdapterRepository):
    # This repository shares the execution database with the later Stage 6.6-6.9
    # evidence and cleanup repositories. Keep the runtime aware of every schema
    # level so it can open the current database without treating newer metadata
    # as incompatible or attempting a downgrade.
    MIGRATION_LEVEL = 9
    EXTRA_TABLES = {
        "execution_capture_sessions", "execution_artifacts", "execution_evidence_captures",
        "execution_veps", "execution_cleanup_receipts", "execution_credential_revocations",
        "execution_post_action_reports", "execution_cti_feedback",
    }
    EXTRA_MIGRATIONS = (
        "006_stage6_6_artifact_evidence_capture.sql",
        "007_stage6_7_vep_construction_integrity.sql",
        "008_stage6_8_cleanup_rollback_post_action_verification.sql",
        "009_stage6_9_closed_loop_cti_pentest_integration.sql",
    )
    EXTRA_TRIGGERS = {
        "execution_capture_sessions_no_update", "execution_capture_sessions_no_delete",
        "execution_artifacts_no_update", "execution_artifacts_no_delete",
        "execution_artifacts_closed", "execution_artifacts_quota",
        "execution_evidence_captures_no_update", "execution_evidence_captures_no_delete",
        "execution_evidence_captures_terminal", "execution_veps_no_update", "execution_veps_no_delete",
        "execution_veps_terminal", "execution_cleanup_receipts_no_update",
        "execution_cleanup_receipts_no_delete", "execution_credential_revocations_no_update",
        "execution_credential_revocations_no_delete", "execution_post_action_reports_no_update",
        "execution_post_action_reports_no_delete", "execution_cleanup_receipts_owned",
        "execution_credential_revocations_scoped", "execution_post_action_reports_terminal",
        "execution_cti_feedback_no_update", "execution_cti_feedback_no_delete",
        "execution_cti_feedback_source",
    }
    INTERMEDIATE_TABLES = {
        6: {"execution_capture_sessions", "execution_artifacts", "execution_evidence_captures"},
        7: {"execution_capture_sessions", "execution_artifacts", "execution_evidence_captures", "execution_veps"},
        8: {
            "execution_capture_sessions", "execution_artifacts", "execution_evidence_captures", "execution_veps",
            "execution_cleanup_receipts", "execution_credential_revocations", "execution_post_action_reports",
        },
    }

    def initialize(self):
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.execute("BEGIN IMMEDIATE")
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    versions = {1: {"execution_repository_meta", "execution_requests"}}
                    versions[2] = versions[1] | {"execution_authorizations"}
                    versions[3] = versions[2] | {"execution_gateway_submissions"}
                    versions[4] = versions[3] | {"execution_adapter_invocations", "execution_adapter_results"}
                    versions[5] = versions[4] | {"execution_runtime_attempts", "execution_runtime_events", "execution_runtime_commands"}
                    for level, extra in self.INTERMEDIATE_TABLES.items():
                        versions[level] = versions[5] | extra
                    if self.MIGRATION_LEVEL > 5:
                        versions[self.MIGRATION_LEVEL] = versions[5] | self.EXTRA_TABLES
                    starting_level = 0
                    if tables:
                        if "execution_repository_meta" not in tables:
                            raise ExecutionRepositoryError("foreign runtime repository; no migration performed")
                        meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                        if (meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION
                            or meta["migration_level"] not in versions or tables != versions[meta["migration_level"]]):
                            raise ExecutionRepositoryError("incompatible runtime metadata; no downgrade performed")
                        starting_level = meta["migration_level"]
                    root = Path(__file__).resolve().parents[1] / "execution_migrations"
                    names = ["001_stage6_1_canonical_execution_request_contract.sql", "002_stage6_2_authoritative_execution_authorization.sql",
                        "003_stage6_3_controlled_execution_gateway.sql", "004_stage6_4_authorized_tool_adapters_sandboxing.sql",
                        "005_stage6_5_execution_runtime_control.sql", *self.EXTRA_MIGRATIONS]
                    for name in names[starting_level:]:
                        statement = ""
                        for line in (root / name).read_text(encoding="utf-8").splitlines(keepends=True):
                            statement += line
                            if sqlite3.complete_statement(statement):
                                conn.execute(statement)
                                statement = ""
                        if statement.strip():
                            raise ExecutionRepositoryError("incomplete runtime migration")
                    required_triggers = {
                        "execution_runtime_attempts_no_update", "execution_runtime_attempts_no_delete",
                        "execution_runtime_events_no_update", "execution_runtime_events_no_delete",
                        "execution_runtime_events_terminal", "execution_runtime_commands_no_update",
                        "execution_runtime_commands_no_delete", "execution_adapter_invocations_v5_guard"}
                    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
                    if not (required_triggers | self.EXTRA_TRIGGERS) <= triggers:
                        raise ExecutionRepositoryError("runtime enforcement triggers missing")
                    conn.execute("INSERT OR IGNORE INTO execution_repository_meta VALUES (1,?,?)", (EXECUTION_REPOSITORY_SCHEMA_VERSION, self.MIGRATION_LEVEL))
                    conn.execute("UPDATE execution_repository_meta SET migration_level=? WHERE singleton=1", (self.MIGRATION_LEVEL,))
                self._initialized = True
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("atomic runtime migration failed") from exc

    def migration_level(self):
        self.initialize()
        with closing(self._connect()) as conn:
            meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
            if meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION or meta["migration_level"] != self.MIGRATION_LEVEL:
                raise ExecutionRepositoryError("runtime migration metadata mismatch")
        return self.MIGRATION_LEVEL

    def _command_row(self, row, conn):
        try:
            record = json.loads(row["record_json"])
            if not verify_command(record):
                raise ExecutionRequestIntegrityError("runtime command integrity mismatch")
            expected = {k:record[k] for k in ("command_id", "operation", "mission_id", "attempt_id", "requested_at")}
            expected.update({"command_request_id": record["intake"]["command_request_id"],
                "idempotency_key": record["intake"]["idempotency_key"], "record_sha256": record["integrity"]["canonical_sha256"]})
            if any(row[k] != v for k,v in expected.items()):
                raise ExecutionRequestIntegrityError("runtime command index mismatch")
            for target in record["target_attempts"]:
                a = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (target["attempt_id"],)).fetchone()
                if a is None or a["mission_id"] != record["mission_id"] or a["record_sha256"] != target["attempt_sha256"]:
                    raise ExecutionRequestIntegrityError("runtime command attempt binding mismatch")
            if record["operation"] == "CANCEL" and (record["attempt_id"] != record["intake"]["attempt_id"]
                or len(record["target_attempts"]) != 1
                or record["target_attempts"][0]["attempt_sha256"] != record["intake"]["attempt_sha256"]):
                raise ExecutionRequestIntegrityError("runtime cancel binding mismatch")
            if record["operation"] == "KILL" and (record["attempt_id"] is not None or record["mission_id"] != record["intake"]["mission_id"]):
                raise ExecutionRequestIntegrityError("runtime kill binding mismatch")
            return record
        except (TypeError, ValueError, KeyError) as exc:
            raise ExecutionRequestIntegrityError("unreadable runtime command") from exc

    def _commands(self, conn, mission_id):
        return [self._command_row(r, conn) for r in conn.execute(
            "SELECT * FROM execution_runtime_commands WHERE mission_id=? ORDER BY rowid", (mission_id,))]

    def _runtime_item(self, row, conn):
        try:
            record = json.loads(row["record_json"])
            if not verify_attempt(record):
                raise ExecutionRequestIntegrityError("runtime attempt integrity mismatch")
            expected = {k:record[k] for k in ("attempt_id", "invocation_id", "execution_id", "mission_id", "attempt_number", "owner_id", "authorized_at")}
            expected["record_sha256"] = record["integrity"]["canonical_sha256"]
            if any(row[k] != v for k,v in expected.items()):
                raise ExecutionRequestIntegrityError("runtime attempt index mismatch")
            c = conn.execute("SELECT * FROM execution_adapter_invocations WHERE invocation_id=?", (record["invocation_id"],)).fetchone()
            if c is None:
                raise ExecutionRequestIntegrityError("runtime claim missing")
            invocation = self._item(c, conn)
            claim = invocation["record"]
            if (claim["status"] != "RESERVED" or record["claim_sha256"] != claim["integrity"]["canonical_sha256"]
                or adapter_intake(record["runtime_intake"]) != claim["intake"]
                or any(record[k] != claim[k] for k in ("execution_id", "mission_id", "task_id", "pentest_id", "pentest_task_id"))
                or record["authorized_at"] != claim["reserved_at"]):
                raise ExecutionRequestIntegrityError("runtime exact claim binding mismatch")
            prior = conn.execute("SELECT * FROM execution_runtime_attempts WHERE execution_id=? AND attempt_number<? ORDER BY attempt_number",
                                 (record["execution_id"], record["attempt_number"])).fetchall()
            if len(prior) != record["attempt_number"] - 1:
                raise ExecutionRequestIntegrityError("runtime attempt ordinal gap")
            if prior:
                predecessor = self._runtime_item(prior[-1], conn)
                if (record["retry_of_attempt_id"] != predecessor["attempt_id"]
                    or record["runtime_intake"]["expected_head_sha256"] != predecessor["head_sha256"]
                    or not self.recoverable(predecessor)):
                    raise ExecutionRequestIntegrityError("runtime retry predecessor mismatch")
            elif record["retry_of_attempt_id"] is not None:
                raise ExecutionRequestIntegrityError("first attempt cannot be retry")
            events, before, previous, timestamp = [], None, None, None
            for sequence, e in enumerate(conn.execute("SELECT * FROM execution_runtime_events WHERE attempt_id=? ORDER BY event_sequence", (record["attempt_id"],)), 1):
                event = json.loads(e["record_json"])
                if not verify_event(event):
                    raise ExecutionRequestIntegrityError("runtime event integrity mismatch")
                if (event["attempt_id"] != record["attempt_id"] or event["attempt_sha256"] != record["integrity"]["canonical_sha256"]
                    or event["event_sequence"] != sequence or event["state_before"] != before
                    or event["previous_event_sha256"] != previous
                    or any(e[k] != event[k] for k in ("event_id", "attempt_id", "event_sequence", "event_type", "state_after", "occurred_at"))
                    or e["record_sha256"] != event["integrity"]["canonical_sha256"]):
                    raise ExecutionRequestIntegrityError("runtime event chain/index mismatch")
                at = parse_time(event["occurred_at"], "occurred_at")
                if timestamp is not None and at < timestamp:
                    raise ExecutionRequestIntegrityError("runtime event clock moved backwards")
                if before in TERMINAL:
                    raise ExecutionRequestIntegrityError("runtime terminal state mutated")
                if event["event_type"] == "STOP_REQUESTED":
                    command = conn.execute("SELECT * FROM execution_runtime_commands WHERE command_id=?", (event["data"]["command_id"],)).fetchone()
                    if command is None or self._command_row(command, conn)["integrity"]["canonical_sha256"] != event["data"]["command_sha256"]:
                        raise ExecutionRequestIntegrityError("runtime stop command missing")
                elif event["actor"] != record["owner_id"] and not event["data"].get("recovery_owner_fenced"):
                    raise ExecutionRequestIntegrityError("runtime event producer mismatch")
                if event["event_type"] == "RUNNING" and (event["data"].get("native_worker_ready") is not True
                    or type(event["data"].get("worker_pid")) is not int or event["data"]["worker_pid"] <= 0
                    or event["data"].get("sandbox_backend") not in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}):
                    raise ExecutionRequestIntegrityError("runtime native readiness missing")
                if event["event_type"] == "HEARTBEAT":
                    auth_row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (event["data"]["authorization_id"],)).fetchone()
                    if auth_row is None:
                        raise ExecutionRequestIntegrityError("runtime heartbeat authorization missing")
                    auth = self._authorization_row(auth_row, conn)["record"]
                    if auth["execution_id"] != record["execution_id"] or auth["decision"] != "ALLOW":
                        raise ExecutionRequestIntegrityError("runtime heartbeat authority binding mismatch")
                events.append(event)
                before, previous, timestamp = event["state_after"], event["integrity"]["canonical_sha256"], at
            if not events or events[0]["occurred_at"] != record["authorized_at"]:
                raise ExecutionRequestIntegrityError("runtime genesis missing")
            if before in TERMINAL:
                data = events[-1]["data"]
                if data.get("recovery_owner_fenced") is True:
                    if before != "ABORTED" or data.get("target_io_uncertain") is not True or data.get("adapter_result_sha256") is not None:
                        raise ExecutionRequestIntegrityError("invalid runtime recovery terminal")
                elif (data.get("resources_closed") is not True or invocation["result"] is None
                      or data.get("adapter_result_sha256") != invocation["result"]["integrity"]["canonical_sha256"]):
                    raise ExecutionRequestIntegrityError("runtime terminal result/cleanup mismatch")
                elif before == "SUCCEEDED" and invocation["result"]["status"] != "SUCCEEDED":
                    raise ExecutionRequestIntegrityError("runtime success without successful primitive")
            elif invocation["result"] is not None:
                raise ExecutionRequestIntegrityError("runtime result without atomic terminal event")
            return {"attempt_id": record["attempt_id"], "record": record, "state": before,
                "head_sha256": previous, "events": events, "invocation": invocation,
                "target_io_uncertain": bool(before in TERMINAL and events[-1]["data"].get("target_io_uncertain"))}
        except (TypeError, ValueError, KeyError) as exc:
            raise ExecutionRequestIntegrityError("unreadable runtime attempt") from exc

    @staticmethod
    def retryable(item):
        result = item["invocation"]["result"]
        return (item["state"] in {"FAILED", "TIMEOUT"} and not item["target_io_uncertain"]
                and result is not None and result["semantics"]["target_network_io_performed"] is False
                and item["events"][-1]["data"].get("resources_closed") is True)

    @staticmethod
    def recoverable_aborted(item):
        """An ABORTED attempt proven to have stopped before any target I/O.

        This is deliberately NOT part of retryable(): automatic retry and the
        network-cost/eligibility signals stay FAILED/TIMEOUT-only. Recovery is an
        explicit, freshly-authorized re-attempt for aborts that provably happened
        in the pre-I/O window (a stalled source read, a lost supervisor heartbeat,
        a revoked source). Intentional halts, clock/integrity anomalies and
        I/O-uncertain orphan aborts are excluded by the reason allowlist and the
        sealed-result no-I/O proof below."""
        from .runtime_contract import RECOVERABLE_ABORT_REASONS
        result = item["invocation"]["result"]
        data = item["events"][-1]["data"]
        return (item["state"] == "ABORTED" and not item["target_io_uncertain"]
                and data.get("resources_closed") is True
                and data.get("reason_code") in RECOVERABLE_ABORT_REASONS
                and result is not None
                and result["semantics"]["target_network_io_performed"] is False)

    @classmethod
    def recoverable(cls, item):
        """Explicit re-attempt admission: a retryable failure or a proven-safe
        ABORTED attempt. Used only by the explicit retry/recovery admission and
        the no-I/O budget release, never to widen automatic retry."""
        return cls.retryable(item) or cls.recoverable_aborted(item)

    def _reservation_gateway(self, gate, items, req):
        # A Recon Stage 6.3 receipt is bound to the immutable ExecutionRequest,
        # not to a particular runtime attempt. Reuse that exact admission for
        # an explicit retry after Stage 6.5 has independently proven that the
        # preceding attempt failed before target I/O. Stage 6.5 still obtains
        # fresh GSS authorization for every attempt and the adapter repository
        # verifies this receipt against the request hash before reserving.
        # Stage 6.4 closes new legacy gateway receipts. For the exact WPT
        # source, Stage 6.5's fresh authorization + durable runtime reservation
        # are the central admission. General Recon still requires its receipt.
        action=req.get("action") or {}
        if (gate is None and action in ({"action_class":"TARGET_RECON","capability_id":"web_technology_fingerprinting","technique":"WEB_TECHNOLOGY_FINGERPRINT"}, {"action_class":"TARGET_RECON","capability_id":"web_surface_enumeration","technique":"BOUNDED_WEB_SURFACE_ENUMERATION"})
            and req.get("parameters",{}).get("source_wpt_intake_id")
            and req.get("target",{}).get("target_type")=="URL"):
            return None
        role = req.get("proposing_agent", {}).get("role")
        if role in {"RECONNAISSANCE", "ENUMERATION"}:
            if gate is None:
                code = "RECON_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION" if role == "RECONNAISSANCE" else "ENUMERATION_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION"
                raise ExecutionSourceRejected(code)
            if gate.get("request_sha256") != req.get("integrity", {}).get("canonical_sha256"):
                code = "RECON_GATEWAY_ADMISSION_REQUEST_BINDING_MISMATCH" if role == "RECONNAISSANCE" else "ENUMERATION_GATEWAY_ADMISSION_REQUEST_BINDING_MISMATCH"
                raise ExecutionSourceRejected(code)
            return gate
        # For non-Recon actions, a predecessor gateway reservation covers
        # only the first attempt.
        return None if any(i["record"]["status"] == "RESERVED" and i["record"]["execution_id"] == req["execution_id"] for i in items) else gate

    def _check_reservation_identity(self, conn, req, items, runtime_context):
        if not runtime_context:
            raise ExecutionSourceRejected("STAGE6_5_RUNTIME_ADMISSION_REQUIRED")
        if any(c["operation"] == "KILL" for c in self._commands(conn, req["mission_id"])):
            raise ExecutionSourceRejected("MISSION_EMERGENCY_KILL_LATCHED")
        rows = conn.execute("SELECT * FROM execution_runtime_attempts WHERE execution_id=? ORDER BY attempt_number", (req["execution_id"],)).fetchall()
        attempts = [self._runtime_item(r, conn) for r in rows]
        legacy = [i for i in items if i["record"]["status"] == "RESERVED" and i["record"]["execution_id"] == req["execution_id"]]
        intake = runtime_context["runtime_intake"]
        if not attempts:
            if legacy or intake["schema_version"] == RETRY_SCHEMA:
                raise ExecutionSourceRejected("LEGACY_OR_MISSING_RUNTIME_ATTEMPT_CANNOT_RETRY")
            return
        if intake["schema_version"] != RETRY_SCHEMA:
            raise ExecutionSourceRejected("EXPLICIT_RUNTIME_RETRY_REQUIRED")
        latest = attempts[-1]
        if intake["retry_of_attempt_id"] != latest["attempt_id"] or intake["expected_head_sha256"] != latest["head_sha256"]:
            raise ExecutionSourceRejected("RETRY_REQUIRES_EXACT_LATEST_TERMINAL_HEAD")
        if len(attempts) >= MAX_ATTEMPTS:
            raise ExecutionSourceRejected("RUNTIME_MAX_ATTEMPTS_EXHAUSTED")
        if not self.recoverable(latest):
            raise ExecutionSourceRejected("RETRY_REQUIRES_PROVEN_NO_TARGET_IO_FAILURE")

    def _network_reservation_cost(self, item, conn):
        row = conn.execute('SELECT * FROM execution_runtime_attempts WHERE invocation_id=?',
                           (item['invocation_id'],)).fetchone()
        # Read and verify the complete terminal event/result chain. Ambiguous,
        # active, successful and post-I/O attempts retain their reservation.
        if row is not None:
            attempt = self._runtime_item(row, conn)
            if self.recoverable(attempt):
                return 0
            if (attempt['state'] == 'SUCCEEDED' and not attempt['target_io_uncertain']
                    and attempt['events'][-1]['data'].get('resources_closed') is True
                    and item['result'] is not None and item['result']['status'] == 'SUCCEEDED'
                    and item['result'].get('operation') in ('WEB_PROFILE_FINGERPRINT','WEB_PROFILE_ENUMERATION')):
                from .wpt_budget import completed_request_cost
                return completed_request_cost(item['result'].get('observation'),
                    item['record']['controls'].get('network_request_cost', 1))
        return super()._network_reservation_cost(item, conn)

    def _reservation_active(self, item, conn):
        if not super()._reservation_active(item, conn):
            return False
        row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE invocation_id=?", (item["invocation_id"],)).fetchone()
        return row is None or self._runtime_item(row, conn)["state"] not in TERMINAL

    def _insert_event(self, conn, record, previous, state, event_type, at, data, actor):
        before = None if previous is None else previous["state_after"]
        if not allowed_transition(before, state, event_type):
            raise ExecutionRequestConflict("invalid runtime transition")
        if previous and parse_time(at, "occurred_at") < parse_time(previous["occurred_at"], "occurred_at"):
            raise ExecutionSourceRejected("RUNTIME_CLOCK_MOVED_BACKWARDS")
        core = {"schema_version": "apts-execution-runtime-event-v1", "control_version": RUNTIME_CONTROL_VERSION,
            "attempt_id": record["attempt_id"], "attempt_sha256": record["integrity"]["canonical_sha256"],
            "event_sequence": 1 if previous is None else previous["event_sequence"] + 1,
            "previous_event_sha256": None if previous is None else previous["integrity"]["canonical_sha256"],
            "state_before": before, "state_after": state, "event_type": event_type,
            "occurred_at": at, "actor": actor, "data": deepcopy(data)}
        event = with_integrity({**core, "event_id": "xevent-" + sha256_hex(core)[:32]}, EVENT_DOMAIN)
        conn.execute("INSERT INTO execution_runtime_events VALUES (?,?,?,?,?,?,?,?)", (
            event["event_id"], record["attempt_id"], event["event_sequence"], event_type, state,
            event["integrity"]["canonical_sha256"], canonical_json(event), at))
        return event

    def _before_reservation_insert(self, conn, claim, runtime_context):
        if claim["status"] != "RESERVED":
            return
        if not runtime_context:
            raise ExecutionSourceRejected("STAGE6_5_RUNTIME_ADMISSION_REQUIRED")
        ordinal = conn.execute("SELECT count(*) FROM execution_runtime_attempts WHERE execution_id=?", (claim["execution_id"],)).fetchone()[0] + 1
        record = with_integrity({"schema_version": "apts-execution-runtime-attempt-v1", "control_version": RUNTIME_CONTROL_VERSION,
            "attempt_id": attempt_id(claim["invocation_id"]), "attempt_number": ordinal,
            "invocation_id": claim["invocation_id"], "claim_sha256": claim["integrity"]["canonical_sha256"],
            **{k:claim[k] for k in ("execution_id", "mission_id", "task_id", "pentest_id", "pentest_task_id")},
            "runtime_intake": deepcopy(runtime_context["runtime_intake"]), "owner_id": runtime_context["owner_id"],
            "retry_of_attempt_id": runtime_context["runtime_intake"].get("retry_of_attempt_id"),
            "state": "AUTHORIZED", "authorized_at": claim["reserved_at"]}, ATTEMPT_DOMAIN)
        conn.execute("INSERT INTO execution_runtime_attempts VALUES (?,?,?,?,?,?,?,?,?)", (
            record["attempt_id"], claim["invocation_id"], claim["execution_id"], claim["mission_id"], ordinal,
            record["owner_id"], record["integrity"]["canonical_sha256"], canonical_json(record), claim["reserved_at"]))
        self._insert_event(conn, record, None, "AUTHORIZED", "AUTHORIZED", claim["reserved_at"],
                           {"authorization_id": claim["authorization_id"]}, record["owner_id"])

    def get_attempt(self, identity):
        require_id(identity, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            # One snapshot for the event chain and result tables during a commit.
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            return None if row is None else self._runtime_item(row, conn)

    def find_runtime_intake(self, intake):
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            old = self._find_adapter(conn, adapter_intake(intake))
            if old is None:
                return None
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE invocation_id=?", (old["invocation_id"],)).fetchone()
            if row is None:
                if 'AUTHORITATIVE_DENY' in old['record']['reason_codes']:
                    raise ExecutionSourceRejected(';'.join(old['record']['reason_codes']))
                raise ExecutionSourceRejected("HISTORICAL_ADAPTER_INTAKE_NOT_RUNTIME_ADMISSION")
            item = self._runtime_item(row, conn)
            if item["record"]["runtime_intake"] != intake:
                raise ExecutionRequestConflict("runtime intake idempotency content conflict")
            return item

    def list_attempts(self, execution_id=None, limit=100):
        if execution_id is not None:
            require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExecutionRequestValidationError("runtime list limit must be 1-500")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM execution_runtime_attempts" + (" WHERE execution_id=?" if execution_id else "")
                + " ORDER BY rowid LIMIT ?", ([execution_id] if execution_id else []) + [limit]).fetchall()
            return [self._runtime_item(r, conn) for r in rows]

    def live_attempts(self):
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT a.* FROM execution_runtime_attempts a WHERE NOT EXISTS (SELECT 1 FROM execution_runtime_events e "
                "WHERE e.attempt_id=a.attempt_id AND e.state_after IN ('SUCCEEDED','FAILED','TIMEOUT','CANCELLED','ABORTED')) ORDER BY a.rowid").fetchall()
            return [self._runtime_item(r, conn) for r in rows]

    def legacy_quarantined_count(self):
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT a.* FROM execution_adapter_invocations a WHERE a.status='RESERVED' "
                "AND NOT EXISTS (SELECT 1 FROM execution_runtime_attempts r WHERE r.invocation_id=a.invocation_id) "
                "AND NOT EXISTS (SELECT 1 FROM execution_adapter_results o WHERE o.invocation_id=a.invocation_id)").fetchall()
            for row in rows:
                self._item(row,conn)
            return len(rows)

    def append_event(self, identity, state, event_type, at, data, owner_id):
        self.initialize()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("runtime attempt not found")
            item = self._runtime_item(row, conn)
            if item["record"]["owner_id"] != owner_id:
                raise ExecutionSourceRejected("RUNTIME_OWNER_MISMATCH")
            if item["state"] in TERMINAL:
                raise ExecutionRequestConflict("runtime terminal state is final")
            if self._stop_in(conn, item) is not None and event_type in {"DISPATCHED", "RUNNING", "HEARTBEAT"}:
                raise ExecutionSourceRejected("RUNTIME_STOP_ALREADY_REQUESTED")
            if state in TERMINAL:
                raise ExecutionSourceRejected("TERMINAL_REQUIRES_ATOMIC_RESULT_FINALIZATION")
            self._insert_event(conn, item["record"], item["events"][-1], state, event_type, at, data, owner_id)

    def _stop_in(self, conn, item):
        commands = self._commands(conn, item["record"]["mission_id"])
        if any(c["operation"] == "KILL" for c in commands):
            return "ABORTED", "MISSION_EMERGENCY_KILL"
        if any(c["operation"] == "CANCEL" and c["attempt_id"] == item["attempt_id"] and c["outcome"] == "STOP_REQUESTED" for c in commands):
            return "CANCELLED", "OPERATOR_CANCELLED"
        return None

    def requested_stop(self, identity):
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("runtime attempt not found")
            return self._stop_in(conn, self._runtime_item(row, conn))

    def append_command(self, intake, operation, at):
        self.initialize()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM execution_runtime_commands WHERE command_request_id=? OR idempotency_key=?",
                               (intake["command_request_id"], intake["idempotency_key"])).fetchall()
            if old:
                if len(old) != 1:
                    raise ExecutionRequestConflict("runtime command identities conflict")
                stored = self._command_row(old[0], conn)
                if stored["intake"] != intake or stored["operation"] != operation:
                    raise ExecutionRequestConflict("runtime command idempotency conflict")
                return stored, False
            if operation == "CANCEL":
                rows = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (intake["attempt_id"],)).fetchall()
                if not rows:
                    raise ExecutionSourceNotFound("runtime attempt not found")
                items = [self._runtime_item(rows[0], conn)]
                if items[0]["record"]["integrity"]["canonical_sha256"] != intake["attempt_sha256"]:
                    raise ExecutionRequestIntegrityError("cancel attempt hash mismatch")
                mission_id = items[0]["record"]["mission_id"]
            else:
                mission_id = intake["mission_id"]
                exists = conn.execute("SELECT 1 FROM execution_requests WHERE mission_id=?", (mission_id,)).fetchone()
                if exists is None:
                    raise ExecutionSourceNotFound("execution mission not found")
                items = [self._runtime_item(r, conn) for r in conn.execute("SELECT * FROM execution_runtime_attempts WHERE mission_id=? ORDER BY rowid", (mission_id,))]
            targets = [{"attempt_id":i["attempt_id"], "attempt_sha256":i["record"]["integrity"]["canonical_sha256"],
                        "state":i["state"], "head_sha256":i["head_sha256"]} for i in items]
            outcome = "KILL_LATCHED" if operation == "KILL" else ("TERMINAL_NOOP" if items[0]["state"] in TERMINAL else "STOP_REQUESTED")
            record = with_integrity({"schema_version": "apts-execution-runtime-command-v1", "control_version": RUNTIME_CONTROL_VERSION,
                "command_id": "xcommand-" + sha256_hex(intake)[:32], "intake": deepcopy(intake), "operation": operation,
                "mission_id": mission_id, "attempt_id": None if operation == "KILL" else intake["attempt_id"],
                "target_attempts": targets, "outcome": outcome, "requested_at": at}, COMMAND_DOMAIN)
            conn.execute("INSERT INTO execution_runtime_commands VALUES (?,?,?,?,?,?,?,?,?)", (
                record["command_id"], intake["command_request_id"], intake["idempotency_key"], operation, mission_id,
                record["attempt_id"], record["integrity"]["canonical_sha256"], canonical_json(record), at))
            for item in items:
                if item["state"] not in TERMINAL:
                    self._insert_event(conn, item["record"], item["events"][-1], item["state"], "STOP_REQUESTED", at,
                        {"command_id":record["command_id"], "command_sha256":record["integrity"]["canonical_sha256"]}, "LOCAL_OPERATOR")
            return record, True

    def finalize(self, identity, result, state, reason, at, owner_id, *, diagnostics=None):
        if state not in TERMINAL or not verify_adapter_result(result):
            raise ExecutionRequestIntegrityError("invalid runtime finalization")
        self.initialize()
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("runtime attempt not found")
            item = self._runtime_item(row, conn)
            if item["record"]["owner_id"] != owner_id:
                raise ExecutionSourceRejected("RUNTIME_OWNER_MISMATCH")
            if item["state"] in TERMINAL:
                raise ExecutionRequestConflict("runtime terminal state is final")
            stopped = self._stop_in(conn, item)
            if stopped:
                state, reason = stopped
            claim = item["invocation"]["record"]
            if result["invocation_id"] != claim["invocation_id"]:
                raise ExecutionRequestIntegrityError("runtime finalization invocation mismatch")
            conn.execute("INSERT INTO execution_adapter_results VALUES (?,?,?,?,?,?)", (
                result["invocation_id"], result["boundary_authorization_id"], result["status"],
                result["integrity"]["canonical_sha256"], canonical_json(result), result["completed_at"]))
            self._insert_event(conn, item["record"], item["events"][-1], state, state, at,
                {"reason_code":reason, "resources_closed":True, "target_io_uncertain":False,
                 "adapter_result_sha256":result["integrity"]["canonical_sha256"],
                 **({"diagnostics":diagnostics} if diagnostics else {})}, owner_id)
            # Verify every result/authorization projection before committing.
            return self._runtime_item(row, conn)

    def recover_orphans(self, at, recovery_owner):
        """Caller holds the exclusive OS lock; no target redispatch or result invention."""
        recovered = []
        for orphan in self.live_attempts():
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (orphan["attempt_id"],)).fetchone()
                item = self._runtime_item(row, conn)
                if item["state"] in TERMINAL:
                    continue
                self._insert_event(conn, item["record"], item["events"][-1], "ABORTED", "ABORTED", at,
                    {"reason_code":"RECOVERY_ORPHAN_NO_REDISPATCH", "recovery_owner_fenced":True,
                     "target_io_uncertain":True, "adapter_result_sha256":None}, recovery_owner)
                recovered.append(item["attempt_id"])
        return recovered

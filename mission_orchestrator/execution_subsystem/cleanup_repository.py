"""Durable local revocation and immutable post-action reports over exact evidence lineage."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

from .adapter_contract import verify_adapter_result
from .authorization_contract import parse_time
from .cleanup_contract import (CONTROL_VERSION, EXPORT_SCHEMA, RECEIPT_DOMAIN, RECEIPT_SCHEMA,
    build_report, build_revocation, canonical_cleanup_contract, normalize_intake,
    verify_post_action_export, verify_receipt, verify_report, verify_revocation)
from .cleanup_resources import resources_verified
from .evidence_repository import ExecutionEvidenceRepository
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, require_id, with_integrity)
from .request_repository import ExecutionRepositoryError
from .runtime_contract import TERMINAL
from .vep_repository import ExecutionVEPRepository


class ExecutionCleanupRepository(ExecutionVEPRepository):
    MIGRATION_LEVEL = 8
    CLEANUP_TABLES = {"execution_cleanup_receipts", "execution_credential_revocations", "execution_post_action_reports"}
    EXTRA_TABLES = ExecutionVEPRepository.EXTRA_TABLES | CLEANUP_TABLES
    INTERMEDIATE_TABLES = {6:ExecutionEvidenceRepository.EXTRA_TABLES, 7:ExecutionVEPRepository.EXTRA_TABLES}
    EXTRA_MIGRATIONS = (*ExecutionVEPRepository.EXTRA_MIGRATIONS, "008_stage6_8_cleanup_rollback_post_action_verification.sql")
    EXTRA_TRIGGERS = ExecutionVEPRepository.EXTRA_TRIGGERS | {
        f"{t}_no_{op}" for t in CLEANUP_TABLES for op in ("update", "delete")} | {
        "execution_cleanup_receipts_owned", "execution_credential_revocations_scoped", "execution_post_action_reports_terminal"}

    def _insert_event(self, conn, record, previous, state, event_type, at, data, actor):
        if event_type == "AUTHORIZED":
            data = {**data, "cleanup_contract_sha256":canonical_cleanup_contract()["integrity"]["canonical_sha256"]}
        event = super()._insert_event(conn, record, previous, state, event_type, at, data, actor)
        if state in TERMINAL:
            row = conn.execute("SELECT record_json FROM execution_adapter_invocations WHERE invocation_id=?", (record["invocation_id"],)).fetchone()
            claim = json.loads(row["record_json"])
            self._revoke(conn, record, claim["controls"]["credential_lease_id"], at)
        return event

    @staticmethod
    def _revocation_row(row):
        try:
            value = json.loads(row["record_json"])
            expected = {k:value[k] for k in ("lease_id", "execution_id", "attempt_id", "revoked_at")}
            expected["record_sha256"] = value["integrity"]["canonical_sha256"]
            if (not verify_revocation(value) or canonical_json(value) != row["record_json"]
                or any(row[k] != v for k,v in expected.items())):
                raise ExecutionRequestIntegrityError("local credential revocation record/index mismatch")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("invalid credential revocation record") from exc

    def _get_revocation(self, conn, lease_id, execution_id):
        if not lease_id:
            return None
        row = conn.execute("SELECT * FROM execution_credential_revocations WHERE lease_id=? AND execution_id=?", (lease_id, execution_id)).fetchone()
        if row is None:
            return None
        value = self._revocation_row(row)
        source = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (value["attempt_id"],)).fetchone()
        if source is None:
            raise ExecutionRequestIntegrityError("credential revocation source missing")
        item = self._runtime_item(source, conn)
        if (item["record"]["execution_id"] != execution_id
            or item["record"]["integrity"]["canonical_sha256"] != value["attempt_sha256"]
            or item["invocation"]["record"]["controls"]["credential_lease_id"] != lease_id
            or parse_time(value["revoked_at"], "revoked_at") < parse_time(item["record"]["authorized_at"], "authorized_at")):
            raise ExecutionRequestIntegrityError("credential revocation source/lease/time mismatch")
        return value

    def _revoke(self, conn, attempt, lease_id, at):
        if not lease_id:
            return None
        old = self._get_revocation(conn, lease_id, attempt["execution_id"])
        if old is not None:
            return old
        value = build_revocation(attempt, lease_id, at)
        conn.execute("INSERT INTO execution_credential_revocations VALUES (?,?,?,?,?,?)", (
            lease_id, attempt["execution_id"], attempt["attempt_id"], value["integrity"]["canonical_sha256"], canonical_json(value), at))
        return value

    def lease_revoked(self, lease_id, execution_id):
        require_id(lease_id, "lease_id", "credlease-")
        require_id(execution_id, "execution_id", "exec-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            return self._get_revocation(conn, lease_id, execution_id) is not None

    def persist_cleanup(self, identity, owner_id, result, resources, at):
        """Only the owned runtime calls this before atomic terminal finalization."""
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
                if row is None:
                    raise ExecutionSourceNotFound("cleanup attempt not found")
                item = self._runtime_item(row, conn)
                attempt = item["record"]
                if item["state"] in TERMINAL or attempt["owner_id"] != owner_id:
                    raise ExecutionSourceRejected("CLEANUP_REQUIRES_ACTIVE_EXACT_RUNTIME_OWNER")
                if (not verify_adapter_result(result) or result["invocation_id"] != attempt["invocation_id"]
                    or result["claim_sha256"] != attempt["claim_sha256"]
                    or any(result[k] != attempt[k] for k in ("execution_id", "mission_id", "task_id", "pentest_id", "pentest_task_id"))
                    or result["controls"] != item["invocation"]["record"]["controls"]
                    or result["registry_sha256"] != item["invocation"]["record"]["registry_sha256"]
                    or parse_time(at, "verified_at") < parse_time(result["completed_at"], "completed_at")):
                    raise ExecutionRequestIntegrityError("cleanup result/claim/time mismatch")
                core = {"schema_version":RECEIPT_SCHEMA, "control_version":CONTROL_VERSION,
                    "attempt_id":identity, "execution_id":attempt["execution_id"], "owner_id":owner_id,
                    "attempt_sha256":attempt["integrity"]["canonical_sha256"], "claim_sha256":attempt["claim_sha256"],
                    "adapter_result_sha256":result["integrity"]["canonical_sha256"],
                    "contract_sha256":canonical_cleanup_contract()["integrity"]["canonical_sha256"],
                    "resources":resources, "verified_at":at,
                    "local_resources_verified":resources_verified(resources["after_rollback"])
                        and not resources["rollback_errors"] and not resources["interrupt_cleanup_errors"]}
                value = with_integrity(core, RECEIPT_DOMAIN)
                if not verify_receipt(value):
                    raise ExecutionRequestIntegrityError("invalid native cleanup receipt")
                self._revoke(conn, attempt, item["invocation"]["record"]["controls"]["credential_lease_id"], at)
                conn.execute("INSERT INTO execution_cleanup_receipts VALUES (?,?,?,?,?,?,?)", (
                    identity, attempt["execution_id"], owner_id, result["integrity"]["canonical_sha256"],
                    value["integrity"]["canonical_sha256"], canonical_json(value), at))
                return value
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("atomic cleanup receipt/revocation persistence failed") from exc

    def _receipt(self, conn, identity):
        row = conn.execute("SELECT * FROM execution_cleanup_receipts WHERE attempt_id=?", (identity,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["record_json"])
            expected = {k:value[k] for k in ("attempt_id", "execution_id", "owner_id", "adapter_result_sha256", "verified_at")}
            expected["record_sha256"] = value["integrity"]["canonical_sha256"]
            if (not verify_receipt(value) or canonical_json(value) != row["record_json"]
                or any(row[k] != v for k,v in expected.items())):
                raise ExecutionRequestIntegrityError("cleanup receipt index/hash mismatch")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("invalid cleanup receipt") from exc

    def _post_inputs(self, conn, vep_id, attempt_id):
        row = conn.execute("SELECT * FROM execution_veps WHERE vep_id=? AND attempt_id=?", (vep_id, attempt_id)).fetchone()
        if row is None:
            raise ExecutionSourceNotFound("post-action requires an existing exact scoped VEP")
        inputs = self._inputs(conn, attempt_id)
        vep = self._vep_row(conn, row, inputs)
        receipt = self._receipt(conn, attempt_id)
        lease = inputs[0]["claim"]["controls"]["credential_lease_id"]
        revocation = self._get_revocation(conn, lease, vep["execution_id"])
        return vep, receipt, revocation, inputs[2]

    @staticmethod
    def _match_post_intake(intake, vep):
        snapshot = vep["execution_snapshot"]
        expected = {"attempt_id":vep["attempt_id"], "vep_id":vep["vep_id"],
            "vep_sha256":vep["integrity"]["canonical_sha256"],
            "envelope_sha256":snapshot["envelope"]["integrity"]["canonical_sha256"],
            "evidence_sha256":vep["evidence"]["integrity"]["canonical_sha256"],
            "expected_head_sha256":vep["evidence"]["terminal_event_sha256"]}
        if any(intake[k] != v for k,v in expected.items()):
            raise ExecutionRequestIntegrityError("post-action exact VEP/envelope/evidence/terminal references mismatch")

    def _report_row(self, conn, row, inputs=None):
        try:
            value = json.loads(row["record_json"])
            vep, receipt, revocation, _ = inputs or self._post_inputs(conn, row["vep_id"], row["attempt_id"])
            expected = {k:value[k] for k in ("post_action_id", "attempt_id", "execution_id", "vep_id", "vep_sha256",
                "terminal_event_sha256", "state", "evaluated_at")}
            expected["record_sha256"] = value["integrity"]["canonical_sha256"]
            if (canonical_json(value) != row["record_json"] or any(row[k] != v for k,v in expected.items())
                or not verify_report(value, vep, receipt, revocation)):
                raise ExecutionRequestIntegrityError("post-action report index/derived-state/lineage mismatch")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("invalid post-action report") from exc

    def complete_post_action(self, payload, at):
        intake = normalize_intake(payload)
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                inputs = self._post_inputs(conn, intake["vep_id"], intake["attempt_id"])
                self._match_post_intake(intake, inputs[0])
                old = conn.execute("SELECT * FROM execution_post_action_reports WHERE attempt_id=?", (intake["attempt_id"],)).fetchone()
                if old is not None:
                    return self._report_row(conn, old, inputs), False
                value = build_report(*inputs[:3], at)
                columns = ("post_action_id", "attempt_id", "execution_id", "vep_id", "vep_sha256",
                    "terminal_event_sha256", "state", "record_sha256", "record_json", "evaluated_at")
                values = [value[k] for k in columns[:7]] + [value["integrity"]["canonical_sha256"], canonical_json(value), at]
                conn.execute("INSERT INTO execution_post_action_reports ("+",".join(columns)+") VALUES ("+",".join("?" for _ in columns)+")", values)
                row = conn.execute("SELECT * FROM execution_post_action_reports WHERE post_action_id=?", (value["post_action_id"],)).fetchone()
                return self._report_row(conn, row, inputs), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("atomic post-action report failed; execution not redispatched") from exc

    def get_post_action(self, identity, attempt_id, *, export=False):
        require_id(identity, "post_action_id", "xcleanup-")
        require_id(attempt_id, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_post_action_reports WHERE post_action_id=? AND attempt_id=?", (identity, attempt_id)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("post-action report not found in exact attempt")
            inputs = self._post_inputs(conn, row["vep_id"], attempt_id)
            value = self._report_row(conn, row, inputs)
            if not export:
                return value
            vep, receipt, revocation, pairs = inputs
            out = {"schema_version":EXPORT_SCHEMA, "report":value, "vep_export":self._export(vep, pairs),
                "receipt":receipt, "revocation":revocation}
            if not verify_post_action_export(out):
                raise ExecutionRequestIntegrityError("post-action export failed retained-byte verification")
            return out

    def list_post_actions(self, execution_id, limit=100):
        require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExecutionRequestValidationError("post-action list limit must be 1-100")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM execution_post_action_reports WHERE execution_id=? ORDER BY evaluated_at,post_action_id LIMIT ?", (execution_id, limit))
            return [self._report_row(conn, r) for r in rows]

    def get_cleanup_status(self, identity):
        require_id(identity, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("cleanup runtime attempt not found")
            item = self._runtime_item(row, conn)
            report = conn.execute("SELECT * FROM execution_post_action_reports WHERE attempt_id=?", (identity,)).fetchone()
            return {"attempt_id":identity, "runtime_state":item["state"],
                "enrolled":item["events"][0]["data"].get("cleanup_contract_sha256") == canonical_cleanup_contract()["integrity"]["canonical_sha256"],
                "cleanup_receipt_available":conn.execute("SELECT 1 FROM execution_cleanup_receipts WHERE attempt_id=?", (identity,)).fetchone() is not None,
                "post_action_report":None if report is None else self._report_row(conn, report),
                "target_io_uncertain":item["target_io_uncertain"], "read_only":True}

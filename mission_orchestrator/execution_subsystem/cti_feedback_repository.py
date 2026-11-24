"""Execution owns feedback; CTI consumes it through a read-only source."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

from .cleanup_repository import ExecutionCleanupRepository
from .cti_feedback_contract import (EXPORT_SCHEMA, build_feedback, normalize_intake,
    verify_feedback, verify_feedback_export)
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, canonical_json, require_id)
from .request_repository import ExecutionRepositoryError, EXECUTION_REPOSITORY_SCHEMA_VERSION


class ExecutionCTIFeedbackRepository(ExecutionCleanupRepository):
    MIGRATION_LEVEL = 9
    EXTRA_TABLES = ExecutionCleanupRepository.EXTRA_TABLES | {"execution_cti_feedback"}
    INTERMEDIATE_TABLES = {**ExecutionCleanupRepository.INTERMEDIATE_TABLES, 8:ExecutionCleanupRepository.EXTRA_TABLES}
    EXTRA_MIGRATIONS = (*ExecutionCleanupRepository.EXTRA_MIGRATIONS, "009_stage6_9_closed_loop_cti_pentest_integration.sql")
    EXTRA_TRIGGERS = ExecutionCleanupRepository.EXTRA_TRIGGERS | {
        "execution_cti_feedback_no_update", "execution_cti_feedback_no_delete", "execution_cti_feedback_source"}

    def _feedback_inputs(self, conn, post_action_id, attempt_id):
        row = conn.execute("SELECT * FROM execution_post_action_reports WHERE post_action_id=? AND attempt_id=?",
            (post_action_id, attempt_id)).fetchone()
        if row is None:
            raise ExecutionSourceNotFound("feedback requires an existing exact scoped post-action report")
        inputs = self._post_inputs(conn, row["vep_id"], attempt_id)
        report = self._report_row(conn, row, inputs)
        vep, receipt, revocation, pairs = inputs
        return {"schema_version":"apts-post-action-offline-export-v1", "report":report,
            "vep_export":self._export(vep, pairs), "receipt":receipt, "revocation":revocation}

    def _feedback_row(self, conn, row, inputs=None):
        try:
            value = json.loads(row["record_json"])
            source = inputs or self._feedback_inputs(conn, row["post_action_id"], row["attempt_id"])
            expected = {k:value[k] for k in ("feedback_id", "attempt_id", "execution_id", "created_at")}
            expected.update({k:value["source_references"][k] for k in
                ("post_action_id", "post_action_sha256", "vep_id", "vep_sha256")})
            expected["record_sha256"] = value["integrity"]["canonical_sha256"]
            if (canonical_json(value) != row["record_json"] or any(row[k] != v for k,v in expected.items())
                or not verify_feedback(value, source)):
                raise ExecutionRequestIntegrityError("CTI feedback index/derived-state/source mismatch")
            return value, source
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("invalid CTI feedback record") from exc

    def create_feedback(self, payload, at):
        intake = normalize_intake(payload)
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                source = self._feedback_inputs(conn, intake["post_action_id"], intake["attempt_id"])
                vep, report = source["vep_export"]["vep"], source["report"]
                if (intake["vep_id"] != vep["vep_id"] or intake["vep_sha256"] != vep["integrity"]["canonical_sha256"]
                    or intake["post_action_sha256"] != report["integrity"]["canonical_sha256"]):
                    raise ExecutionRequestIntegrityError("feedback intake exact source hash mismatch")
                old = conn.execute("SELECT * FROM execution_cti_feedback WHERE attempt_id=?", (intake["attempt_id"],)).fetchone()
                if old:
                    return self._feedback_row(conn, old, source)[0], False
                value = build_feedback(source, at)
                columns = ("feedback_id", "attempt_id", "execution_id", "post_action_id", "post_action_sha256",
                    "vep_id", "vep_sha256", "record_sha256", "record_json", "created_at")
                values = [value[k] for k in columns[:3]] + [value["source_references"][k] for k in columns[3:7]]
                values += [value["integrity"]["canonical_sha256"], canonical_json(value), at]
                conn.execute("INSERT INTO execution_cti_feedback VALUES (" + ",".join("?" for _ in columns) + ")", values)
                row = conn.execute("SELECT * FROM execution_cti_feedback WHERE feedback_id=?", (value["feedback_id"],)).fetchone()
                return self._feedback_row(conn, row, source)[0], True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("atomic CTI feedback persistence failed; no execution redispatch") from exc

    def get_feedback(self, identity, attempt_id, *, export=False):
        require_id(identity, "feedback_id", "ctifb-")
        require_id(attempt_id, "attempt_id", "xattempt-")
        self.initialize()
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN")
                row = conn.execute("SELECT * FROM execution_cti_feedback WHERE feedback_id=? AND attempt_id=?",
                    (identity, attempt_id)).fetchone()
                if row is None:
                    raise ExecutionSourceNotFound("CTI feedback not found in exact attempt")
                value, source = self._feedback_row(conn, row)
                if not export:
                    return value
                out = {"schema_version":EXPORT_SCHEMA, "feedback":value, "post_action_export":source}
                if not verify_feedback_export(out):
                    raise ExecutionRequestIntegrityError("feedback export failed retained-byte verification")
                return out
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("CTI feedback source unavailable") from exc

    def list_feedback(self, execution_id, limit=100):
        require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExecutionRequestValidationError("feedback list limit must be 1-100")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM execution_cti_feedback WHERE execution_id=? ORDER BY created_at,feedback_id LIMIT ?",
                (execution_id, limit))
            return [self._feedback_row(conn, row)[0] for row in rows]


class ReadOnlyExecutionFeedbackSource(ExecutionCTIFeedbackRepository):
    """Never initializes or migrates Execution; scope/hash/retained bytes are verified on every read."""
    def _connect(self):
        conn = sqlite3.connect(self.sqlite_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def initialize(self):
        try:
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                if (row is None or row["migration_level"] != 9 or row["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION):
                    raise ExecutionRepositoryError("CTI source requires exact Execution migration 9")
                triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
                if not self.EXTRA_TRIGGERS <= triggers:
                    raise ExecutionRequestIntegrityError("Execution feedback enforcement triggers missing")
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("read-only Execution CTI source unavailable") from exc

"""Atomic immutable VEP persistence and read-through audits of original evidence bytes."""
from __future__ import annotations

import base64
from contextlib import closing
import json
import sqlite3

from .evidence_repository import ExecutionEvidenceRepository
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, require_id)
from .request_repository import ExecutionRepositoryError
from .runtime_contract import TERMINAL
from .vep_contract import (EXPORT_SCHEMA, SEMANTICS, build_vep, normalize_vep_intake,
    verify_vep, verify_vep_export)


class ExecutionVEPRepository(ExecutionEvidenceRepository):
    MIGRATION_LEVEL = 7
    EXTRA_TABLES = ExecutionEvidenceRepository.EXTRA_TABLES | {"execution_veps"}
    INTERMEDIATE_TABLES = {6:ExecutionEvidenceRepository.EXTRA_TABLES}
    EXTRA_MIGRATIONS = (*ExecutionEvidenceRepository.EXTRA_MIGRATIONS, "007_stage6_7_vep_construction_integrity.sql")
    EXTRA_TRIGGERS = ExecutionEvidenceRepository.EXTRA_TRIGGERS | {
        "execution_veps_no_update", "execution_veps_no_delete", "execution_veps_terminal"}

    def _inputs(self, conn, identity):
        row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
        if row is None:
            raise ExecutionSourceNotFound("VEP runtime attempt not found")
        item = self._runtime_item(row, conn)
        if item["state"] not in TERMINAL:
            raise ExecutionSourceRejected("VEP_REQUIRES_TERMINAL_ATTEMPT")
        manifest, _ = self._verified_capture(conn, item)
        if manifest is None:
            raise ExecutionSourceRejected("VEP_REQUIRES_STAGE6_6_CAPTURE_NO_LEGACY_BACKFILL")
        command_ids = sorted({e["data"]["command_id"] for e in item["events"] if e["event_type"] == "STOP_REQUESTED"})
        auth_ids = sorted({e["data"]["authorization_id"] for e in item["events"] if e["event_type"] == "HEARTBEAT"})
        commands = [self._command_row(conn.execute("SELECT * FROM execution_runtime_commands WHERE command_id=?", (cid,)).fetchone(), conn)
            for cid in command_ids]
        authorizations = [self._authorization_row(conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (aid,)).fetchone(), conn)["record"]
            for aid in auth_ids]
        snapshot = {"envelope":self._envelope(conn, item["record"]["execution_id"]),
            "attempt":item["record"], "claim":item["invocation"]["record"], "events":item["events"],
            "adapter_result":item["invocation"]["result"], "session":self._session(conn, item["record"]),
            "commands":commands, "authorizations":authorizations}
        pairs = self._artifacts(conn, snapshot["session"])
        return snapshot, manifest, pairs

    @staticmethod
    def _match_intake(intake, snapshot, manifest):
        expected = {"attempt_id":snapshot["attempt"]["attempt_id"],
            "envelope_sha256":snapshot["envelope"]["integrity"]["canonical_sha256"],
            "evidence_sha256":manifest["integrity"]["canonical_sha256"],
            "expected_head_sha256":manifest["terminal_event_sha256"]}
        if any(intake[k] != v for k,v in expected.items()):
            raise ExecutionRequestIntegrityError("VEP exact envelope/evidence/terminal references mismatch")

    @staticmethod
    def _export(value, pairs):
        return {"schema_version":EXPORT_SCHEMA, "vep":value, "artifacts":[
            {"artifact":a, "content_base64":base64.b64encode(p).decode("ascii")} for a,p in pairs],
            "semantics":dict(SEMANTICS)}

    def _vep_row(self, conn, row, inputs=None):
        try:
            value = json.loads(row["record_json"])
            snapshot, manifest, pairs = inputs or self._inputs(conn, row["attempt_id"])
            expected = {k:value[k] for k in ("vep_id", "attempt_id", "execution_id", "mission_id", "pentest_id", "finding_id")}
            expected.update({"evidence_id":manifest["evidence_id"], "evidence_sha256":manifest["integrity"]["canonical_sha256"],
                "terminal_event_sha256":manifest["terminal_event_sha256"], "record_sha256":value["integrity"]["canonical_sha256"],
                "constructed_at":value["timestamps"]["constructed_at"]})
            if (any(row[k] != v for k,v in expected.items()) or canonical_json(value) != row["record_json"]
                or not verify_vep(value) or value["execution_snapshot"] != snapshot or value["evidence"] != manifest
                or not verify_vep_export(self._export(value, pairs))):
                raise ExecutionRequestIntegrityError("VEP record/index/source/byte lineage mismatch")
            return value
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise ExecutionRequestIntegrityError("unreadable VEP record") from exc

    def construction_context(self, payload):
        intake = normalize_vep_intake(payload)
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            inputs = self._inputs(conn, intake["attempt_id"])
            self._match_intake(intake, *inputs[:2])
            row = conn.execute("SELECT * FROM execution_veps WHERE attempt_id=?", (intake["attempt_id"],)).fetchone()
            return inputs[0]["envelope"], None if row is None else self._vep_row(conn, row, inputs)

    def construct(self, payload, source, constructed_at):
        intake = normalize_vep_intake(payload)
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                inputs = self._inputs(conn, intake["attempt_id"])
                snapshot, manifest, pairs = inputs
                self._match_intake(intake, snapshot, manifest)
                old = conn.execute("SELECT * FROM execution_veps WHERE attempt_id=?", (intake["attempt_id"],)).fetchone()
                if old is not None:
                    return self._vep_row(conn, old, inputs), False
                value = build_vep(source, snapshot, manifest, constructed_at)
                if not verify_vep_export(self._export(value, pairs)):
                    raise ExecutionRequestIntegrityError("VEP source/artifact export failed verification")
                columns = ("vep_id", "attempt_id", "execution_id", "mission_id", "pentest_id", "finding_id",
                    "evidence_id", "evidence_sha256", "terminal_event_sha256", "record_sha256", "record_json", "constructed_at")
                values = [value[k] for k in columns[:6]] + [manifest["evidence_id"], manifest["integrity"]["canonical_sha256"],
                    manifest["terminal_event_sha256"], value["integrity"]["canonical_sha256"], canonical_json(value), constructed_at]
                conn.execute("INSERT INTO execution_veps (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", values)
                row = conn.execute("SELECT * FROM execution_veps WHERE vep_id=?", (value["vep_id"],)).fetchone()
                return self._vep_row(conn, row, inputs), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("VEP atomic construction failed; no execution or redispatch performed") from exc

    def get_vep(self, identity, attempt_id, *, export=False):
        require_id(identity, "vep_id", "xvep-")
        require_id(attempt_id, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_veps WHERE vep_id=? AND attempt_id=?", (identity, attempt_id)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("VEP not found in exact attempt")
            inputs = self._inputs(conn, attempt_id)
            value = self._vep_row(conn, row, inputs)
            return self._export(value, inputs[2]) if export else value

    def list_veps(self, execution_id, limit=100):
        require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExecutionRequestValidationError("VEP list limit must be an integer between 1 and 100")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM execution_veps WHERE execution_id=? ORDER BY constructed_at,vep_id LIMIT ?", (execution_id, limit))
            return [self._vep_row(conn, row) for row in rows]

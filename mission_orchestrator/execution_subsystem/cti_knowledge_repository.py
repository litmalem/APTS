"""CTI feedback knowledge owner, separate from Execution, Mission, Pentest, and VulnDesk DBs."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock

from .cti_feedback_contract import (KNOWLEDGE_EXPORT_SCHEMA, MAX_EXPORT_BYTES, build_knowledge,
    normalize_update, verify_knowledge_export)
from .execution_contract import (ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceNotFound, canonical_json, require_id)
from .request_repository import ExecutionRepositoryError

SCHEMA = "apts-cti-feedback-repository-v1"
TABLES = {"cti_feedback_meta", "cti_knowledge_revisions"}
TRIGGERS = {"cti_knowledge_no_update", "cti_knowledge_no_delete", "cti_knowledge_chain"}


class CTIKnowledgeRepository:
    def __init__(self, sqlite_path=None, *, read_only=False):
        self.sqlite_path = Path(sqlite_path or os.getenv("APTS_CTI_FEEDBACK_DB")
            or Path(__file__).resolve().parents[1]/"data"/"cti_feedback_repository.db")
        self.read_only = read_only
        self._lock = RLock()

    def _connect(self):
        if self.read_only:
            conn = sqlite3.connect(self.sqlite_path.resolve().as_uri()+"?mode=ro", uri=True, timeout=10)
            conn.execute("PRAGMA query_only=ON")
        else:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.sqlite_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        with self._lock:
            try:
                with closing(self._connect()) as conn, conn:
                    if not self.read_only:
                        conn.execute("BEGIN IMMEDIATE")
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    if not tables and not self.read_only:
                        sql = (Path(__file__).resolve().parents[1]/"cti_feedback_migrations"/"001_stage6_9_cti_knowledge_feedback.sql").read_text()
                        statement = ""
                        for line in sql.splitlines(keepends=True):
                            statement += line
                            if sqlite3.complete_statement(statement):
                                conn.execute(statement)
                                statement = ""
                        if statement.strip():
                            raise ExecutionRepositoryError("incomplete CTI migration")
                        conn.execute("INSERT INTO cti_feedback_meta VALUES (1,?,1)", (SCHEMA,))
                        tables = TABLES
                    if tables != TABLES:
                        raise ExecutionRepositoryError("CTI feedback database has foreign or incomplete schema")
                    meta = conn.execute("SELECT * FROM cti_feedback_meta WHERE singleton=1").fetchone()
                    if meta is None or meta["schema_version"] != SCHEMA or meta["migration_level"] != 1:
                        raise ExecutionRepositoryError("CTI feedback metadata mismatch; no downgrade")
                    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
                    if not TRIGGERS <= triggers:
                        raise ExecutionRequestIntegrityError("CTI knowledge enforcement triggers missing")
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("CTI knowledge repository unavailable") from exc

    def _history(self, conn, knowledge_id, through=None):
        quota = conn.execute("SELECT count(*),coalesce(sum(length(CAST(record_json AS BLOB))+length(CAST(feedback_export_json AS BLOB))),0) "
            "FROM cti_knowledge_revisions WHERE knowledge_id=? AND revision<=?",
            (knowledge_id, 1000 if through is None else through)).fetchone()
        if quota[0] > 1000 or quota[1] > MAX_EXPORT_BYTES:
            raise ExecutionRequestIntegrityError("CTI knowledge chain storage byte quota exceeded")
        rows = conn.execute("SELECT * FROM cti_knowledge_revisions WHERE knowledge_id=? AND revision<=? ORDER BY revision",
            (knowledge_id, 1000 if through is None else through)).fetchall()
        if not rows:
            return []
        try:
            pairs = []
            for row in rows:
                record = json.loads(row["record_json"])
                source = json.loads(row["feedback_export_json"])
                expected = {k:record[k] for k in ("revision_id", "knowledge_id", "revision", "previous_revision_sha256", "feedback_id", "updated_at")}
                expected.update(mission_id=record["subject"]["mission_id"], record_sha256=record["integrity"]["canonical_sha256"])
                if (any(row[k] != v for k,v in expected.items()) or row["record_json"] != canonical_json(record)
                    or row["feedback_export_json"] != canonical_json(source)):
                    raise ExecutionRequestIntegrityError("CTI knowledge index/snapshot mismatch")
                pairs.append({"record":record, "feedback_export":source})
            out = {"schema_version":KNOWLEDGE_EXPORT_SCHEMA, "knowledge_id":knowledge_id, "revisions":pairs}
            if not verify_knowledge_export(out) or len(canonical_json(out).encode()) > MAX_EXPORT_BYTES:
                raise ExecutionRequestIntegrityError("CTI knowledge chain/retained bytes/derived assessment mismatch")
            if through is not None and pairs[-1]["record"]["revision"] != through:
                raise ExecutionRequestIntegrityError("CTI knowledge revision ordinal gap")
            return pairs
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("CTI knowledge revision is unreadable") from exc

    def import_feedback(self, payload, source, at):
        if self.read_only:
            raise ExecutionRepositoryError("read-only CTI consumer cannot import")
        intake = normalize_update(payload)
        # Resolve only through a trusted local read-only Execution source, never caller JSON.
        exported = source.get_feedback(intake["feedback_id"], intake["attempt_id"], export=True)
        self.initialize()
        try:
            with self._lock, closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                knowledge_id = exported["feedback"]["knowledge_id"]
                pairs = self._history(conn, knowledge_id)
                old = conn.execute("SELECT * FROM cti_knowledge_revisions WHERE feedback_id=?", (intake["feedback_id"],)).fetchone()
                if old:
                    if old["knowledge_id"] != knowledge_id:
                        raise ExecutionRequestIntegrityError("knowledge feedback subject mismatch")
                    pair = next(p for p in pairs if p["record"]["revision_id"] == old["revision_id"])
                    if canonical_json(pair["record"]["intake"]) != canonical_json(intake):
                        raise ExecutionRequestConflict("feedback already imported with different head/intake")
                    if pair["feedback_export"] != exported:
                        raise ExecutionRequestIntegrityError("knowledge historical feedback snapshot changed")
                    return pair["record"], False
                previous = pairs[-1]["record"] if pairs else None
                if (intake["expected_revision"] != (0 if previous is None else previous["revision"])
                    or intake["expected_head_sha256"] != (None if previous is None else previous["integrity"]["canonical_sha256"])):
                    raise ExecutionRequestConflict("CTI knowledge head is stale")
                value = build_knowledge(exported, intake, previous, at)
                prospective = {"schema_version":KNOWLEDGE_EXPORT_SCHEMA, "knowledge_id":knowledge_id,
                    "revisions":[*pairs, {"record":value, "feedback_export":exported}]}
                if len(canonical_json(prospective).encode()) > MAX_EXPORT_BYTES:
                    raise ExecutionRequestValidationError("CTI knowledge chain export byte quota exceeded")
                conn.execute("INSERT INTO cti_knowledge_revisions VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    value["revision_id"], knowledge_id, value["revision"], value["previous_revision_sha256"],
                    value["feedback_id"], value["subject"]["mission_id"], value["integrity"]["canonical_sha256"],
                    canonical_json(value), canonical_json(exported), at))
                return self._history(conn, knowledge_id)[-1]["record"], True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("atomic CTI knowledge revision failed; source feedback remains available") from exc

    def export_knowledge(self, knowledge_id, mission_id, *, through=None):
        require_id(knowledge_id, "knowledge_id", "ctik-")
        require_id(mission_id, "mission_id", "mission-gmo-")
        if through is not None and (type(through) is not int or not 1 <= through <= 1000):
            raise ExecutionRequestValidationError("knowledge revision must be 1-1000")
        self.initialize()
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN")
                scoped = conn.execute("SELECT 1 FROM cti_knowledge_revisions WHERE knowledge_id=? AND mission_id=?",
                    (knowledge_id, mission_id)).fetchone()
                if scoped is None:
                    raise ExecutionSourceNotFound("CTI knowledge not found in exact mission")
                pairs = self._history(conn, knowledge_id, through)
                if not pairs:
                    raise ExecutionSourceNotFound("CTI knowledge revision not found")
                return {"schema_version":KNOWLEDGE_EXPORT_SCHEMA, "knowledge_id":knowledge_id, "revisions":pairs}
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("CTI knowledge read unavailable") from exc

    def list_knowledge(self, mission_id, limit=100):
        require_id(mission_id, "mission_id", "mission-gmo-")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExecutionRequestValidationError("knowledge list limit must be 1-100")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            identities = conn.execute("SELECT DISTINCT knowledge_id FROM cti_knowledge_revisions WHERE mission_id=? ORDER BY knowledge_id LIMIT ?",
                (mission_id, limit)).fetchall()
            return [self._history(conn, r[0])[-1]["record"] for r in identities]

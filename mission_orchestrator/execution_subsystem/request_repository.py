from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from .execution_contract import (
    EXECUTION_REPOSITORY_MIGRATION_LEVEL, ExecutionRequestConflict,
    ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    canonical_json, require_id, verify_canonical_action_envelope,
)

EXECUTION_REPOSITORY_SCHEMA_VERSION = "apts-execution-request-repository-v1"


class ExecutionRepositoryError(RuntimeError):
    pass


def default_execution_repository_path() -> Path:
    configured = os.environ.get("APTS_EXECUTION_DB")
    return (Path(configured).expanduser().resolve() if configured
            else Path(__file__).resolve().parents[1] / "data" / "execution_subsystem.db")


class ExecutionRequestRepository:
    def __init__(self, sqlite_path: str | Path | None = None) -> None:
        self.sqlite_path = Path(sqlite_path).resolve() if sqlite_path else default_execution_repository_path()
        self._lock = RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self) -> None:
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            migration = Path(__file__).resolve().parents[1] / "execution_migrations" / "001_stage6_1_canonical_execution_request_contract.sql"
            try:
                sql = migration.read_text(encoding="utf-8")
                with closing(self._connect()) as conn, conn:
                    conn.execute("BEGIN IMMEDIATE")
                    tables = {row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    owned_tables = {"execution_repository_meta", "execution_requests"}
                    if tables and tables != owned_tables:
                        raise ExecutionRepositoryError("execution database must be empty or contain only the execution request repository")
                    if "execution_repository_meta" in tables:
                        row = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                        if (row is None or row["migration_level"] != EXECUTION_REPOSITORY_MIGRATION_LEVEL
                                or row["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION):
                            raise ExecutionRepositoryError("execution repository metadata is incompatible with Stage 6.1")
                    # Keep metadata preflight and every DDL statement in one transaction.
                    statement = ""
                    for line in sql.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement)
                            statement = ""
                    if statement.strip():
                        raise ExecutionRepositoryError("execution migration contains an incomplete statement")
                    conn.execute("INSERT OR IGNORE INTO execution_repository_meta VALUES (1,?,?)",
                                 (EXECUTION_REPOSITORY_SCHEMA_VERSION, EXECUTION_REPOSITORY_MIGRATION_LEVEL))
                self._initialized = True
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("execution repository initialization failed") from exc

    def migration_level(self) -> int:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT migration_level FROM execution_repository_meta WHERE singleton=1").fetchone()
        if row is None or row[0] != EXECUTION_REPOSITORY_MIGRATION_LEVEL:
            raise ExecutionRepositoryError("execution repository migration metadata mismatch")
        return int(row[0])

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            envelope = json.loads(row["envelope_json"])
            if not verify_canonical_action_envelope(envelope):
                raise ExecutionRequestIntegrityError("stored canonical action envelope failed verification")
            request, intake = envelope["execution_request"], envelope["intake"]
            expected = {
                "execution_id": request["execution_id"], "request_id": intake["request_id"],
                "idempotency_key": intake["idempotency_key"], "mission_id": request["mission_id"],
                "task_id": request["task_id"], "pentest_id": request["pentest_id"],
                "pentest_task_id": envelope["source_binding"]["pentest_task_id"],
                "status": envelope["status"], "envelope_sha256": envelope["integrity"]["canonical_sha256"],
            }
            if any(row[key] != value for key, value in expected.items()):
                raise ExecutionRequestIntegrityError("stored execution request column/envelope mismatch")
            return {"execution_id": request["execution_id"], "status": row["status"],
                    "stored_at": row["stored_at"], "envelope": envelope}
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("stored execution request is unreadable") from exc

    def find_intake(self, intake: dict[str, Any]) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM execution_requests WHERE request_id=? OR idempotency_key=?",
                                (intake["request_id"], intake["idempotency_key"])).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ExecutionRequestConflict("request_id/idempotency_key resolve to different immutable records")
        stored = self._row(rows[0])
        if canonical_json(stored["envelope"]["intake"]) != canonical_json(intake):
            raise ExecutionRequestConflict("request_id/idempotency_key already exists with different content")
        return stored

    def append(self, envelope: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not verify_canonical_action_envelope(envelope):
            raise ExecutionRequestIntegrityError("invalid canonical action envelope")
        self.initialize()
        intake, request = envelope["intake"], envelope["execution_request"]
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute("SELECT * FROM execution_requests WHERE execution_id=? OR request_id=? OR idempotency_key=?",
                                    (request["execution_id"], intake["request_id"], intake["idempotency_key"])).fetchall()
                if rows:
                    if len(rows) != 1:
                        raise ExecutionRequestConflict("execution/request/idempotency identities resolve to different records")
                    stored = self._row(rows[0])
                    if canonical_json(stored["envelope"]) != canonical_json(envelope):
                        raise ExecutionRequestConflict("execution identity already exists with different immutable content")
                    return stored, False
                conn.execute("INSERT INTO execution_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                    request["execution_id"], intake["request_id"], intake["idempotency_key"],
                    request["mission_id"], request["task_id"], request["pentest_id"],
                    envelope["source_binding"]["pentest_task_id"], envelope["status"],
                    envelope["integrity"]["canonical_sha256"], canonical_json(envelope),
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                ))
                row = conn.execute("SELECT * FROM execution_requests WHERE execution_id=?", (request["execution_id"],)).fetchone()
            return self._row(row), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("execution request could not be persisted") from exc

    def get(self, execution_id: str) -> dict[str, Any] | None:
        require_id(execution_id, "execution_id", "exec-")
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_requests WHERE execution_id=?", (execution_id,)).fetchone()
        return None if row is None else self._row(row)

    def list_requests(self, *, mission_id: str | None = None, task_id: str | None = None,
                      pentest_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExecutionRequestValidationError("limit must be an integer between 1 and 500")
        clauses, params = [], []
        for key, value, prefix in (("mission_id", mission_id, "mission-gmo-"),
                                   ("task_id", task_id, "ptask-"), ("pentest_id", pentest_id, "pentest-")):
            if value is not None:
                require_id(value, key, prefix)
                clauses.append(key + "=?")
                params.append(value)
        self.initialize()
        sql = "SELECT * FROM execution_requests"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY stored_at ASC,execution_id ASC LIMIT ?"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, [*params, limit]).fetchall()
        return [self._row(row) for row in rows]

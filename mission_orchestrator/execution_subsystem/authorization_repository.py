from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .authorization_contract import AUTHORIZATION_MIGRATION_LEVEL, verify_authorization_record
from .execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError,
    canonical_json, require_id,
)
from .request_repository import (
    ExecutionRequestRepository, ExecutionRepositoryError, EXECUTION_REPOSITORY_SCHEMA_VERSION,
)


class ExecutionAuthorizationRepository(ExecutionRequestRepository):
    """Atomic v1 -> v2 upgrade; earlier request envelopes remain byte-for-byte."""
    def initialize(self) -> None:
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.execute("BEGIN IMMEDIATE")
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    v1 = {"execution_repository_meta", "execution_requests"}
                    v2 = v1 | {"execution_authorizations"}
                    if tables and tables not in (v1, v2):
                        raise ExecutionRepositoryError("execution database contains foreign or incomplete repository tables")
                    if tables:
                        meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                        if (meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION
                                or meta["migration_level"] not in (1, 2)
                                or tables != (v1 if meta["migration_level"] == 1 else v2)):
                            raise ExecutionRepositoryError("incompatible execution repository metadata; no downgrade performed")
                    for name in ("001_stage6_1_canonical_execution_request_contract.sql", "002_stage6_2_authoritative_execution_authorization.sql"):
                        sql = (Path(__file__).resolve().parents[1] / "execution_migrations" / name).read_text(encoding="utf-8")
                        statement = ""
                        for line in sql.splitlines(keepends=True):
                            statement += line
                            if sqlite3.complete_statement(statement):
                                conn.execute(statement)
                                statement = ""
                        if statement.strip():
                            raise ExecutionRepositoryError("execution migration contains an incomplete statement")
                    conn.execute("INSERT OR IGNORE INTO execution_repository_meta VALUES (1,?,?)",
                                 (EXECUTION_REPOSITORY_SCHEMA_VERSION, AUTHORIZATION_MIGRATION_LEVEL))
                    conn.execute("UPDATE execution_repository_meta SET migration_level=2 WHERE singleton=1")
                self._initialized = True
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("execution authorization migration failed") from exc

    def migration_level(self) -> int:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
        if row is None or row["migration_level"] != 2 or row["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION:
            raise ExecutionRepositoryError("execution authorization migration metadata mismatch")
        return 2

    def _authorization_row(self, row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
        try:
            record = json.loads(row["record_json"])
            if not verify_authorization_record(record):
                raise ExecutionRequestIntegrityError("stored authorization failed verification")
            intake = record["intake"]
            expected = {key: record[key] for key in ("authorization_id", "execution_id", "mission_id", "task_id", "pentest_id", "decision")}
            expected.update({"revalidation_id": intake["revalidation_id"], "idempotency_key": intake["idempotency_key"],
                             "envelope_sha256": intake["envelope_sha256"],
                             "policy_decision_id": record["policy_decision"]["decision_id"],
                             "record_sha256": record["integrity"]["canonical_sha256"]})
            if any(row[key] != value for key, value in expected.items()):
                raise ExecutionRequestIntegrityError("stored authorization index/record mismatch")
            source = conn.execute("SELECT * FROM execution_requests WHERE execution_id=?", (record["execution_id"],)).fetchone()
            if source is None:
                raise ExecutionRequestIntegrityError("authorization request binding is absent")
            envelope = self._row(source)["envelope"]
            if (envelope["integrity"]["canonical_sha256"] != intake["envelope_sha256"]
                    or envelope["execution_request"] != record["evaluation"]["execution_request"]
                    or envelope["source_binding"] != record["evaluation"]["source_binding"]):
                raise ExecutionRequestIntegrityError("authorization does not bind its immutable request")
            return {"authorization_id": record["authorization_id"], "execution_id": record["execution_id"],
                    "stored_at": row["stored_at"], "record": record}
        except (KeyError, ValueError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("stored authorization is unreadable") from exc

    def find_authorization_intake(self, intake: dict[str, Any]) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM execution_authorizations WHERE revalidation_id=? OR idempotency_key=?",
                                (intake["revalidation_id"], intake["idempotency_key"])).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise ExecutionRequestConflict("authorization identities resolve to different records")
            stored = self._authorization_row(rows[0], conn)
        if stored["record"]["intake"] != intake:
            raise ExecutionRequestConflict("authorization idempotency key reused with different content")
        return stored

    def append_authorization(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not verify_authorization_record(record):
            raise ExecutionRequestIntegrityError("invalid authorization record")
        self.initialize()
        intake = record["intake"]
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=? OR revalidation_id=? OR idempotency_key=? OR policy_decision_id=?",
                                    (record["authorization_id"], intake["revalidation_id"], intake["idempotency_key"], record["policy_decision"]["decision_id"])).fetchall()
                if rows:
                    if len(rows) == 1:
                        old = self._authorization_row(rows[0], conn)
                        if old["record"]["intake"] == intake:
                            return old, False
                    raise ExecutionRequestConflict("authorization or PolicyDecision identity was reused")
                conn.execute("INSERT INTO execution_authorizations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    record["authorization_id"], intake["revalidation_id"], intake["idempotency_key"], record["execution_id"],
                    record["mission_id"], record["task_id"], record["pentest_id"], intake["envelope_sha256"],
                    record["policy_decision"]["decision_id"], record["decision"], record["integrity"]["canonical_sha256"],
                    canonical_json(record), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")))
                row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (record["authorization_id"],)).fetchone()
                return self._authorization_row(row, conn), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("authorization could not be persisted") from exc

    def get_authorization(self, authorization_id: str) -> dict[str, Any] | None:
        require_id(authorization_id, "authorization_id", "eauth-")
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (authorization_id,)).fetchone()
            return None if row is None else self._authorization_row(row, conn)

    def list_authorizations(self, execution_id: str, limit: int = 100) -> list[dict[str, Any]]:
        require_id(execution_id, "execution_id", "exec-")
        from .execution_contract import ExecutionRequestValidationError
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExecutionRequestValidationError("authorization list limit must be 1-500")
        self.initialize()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM execution_authorizations WHERE execution_id=? ORDER BY stored_at,authorization_id LIMIT ?",
                                (execution_id, limit)).fetchall()
            return [self._authorization_row(row, conn) for row in rows]

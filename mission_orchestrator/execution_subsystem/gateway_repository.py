from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from .authorization_repository import ExecutionAuthorizationRepository
from .execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    canonical_json, require_id,
)
from .gateway_contract import ADMITTED, make_gateway_record, verify_gateway_record
from .request_repository import EXECUTION_REPOSITORY_SCHEMA_VERSION, ExecutionRepositoryError


def _execution_table_versions() -> dict[int, set[str]]:
    """Return the exact table inventory for each supported shared DB level.

    The gateway can run against a database upgraded by later Stage 6 services.
    It must validate that schema without downgrading its migration marker.
    """
    versions = {1: {"execution_repository_meta", "execution_requests"}}
    versions[2] = versions[1] | {"execution_authorizations"}
    versions[3] = versions[2] | {"execution_gateway_submissions"}
    versions[4] = versions[3] | {"execution_adapter_invocations", "execution_adapter_results"}
    versions[5] = versions[4] | {
        "execution_runtime_attempts", "execution_runtime_events", "execution_runtime_commands",
    }
    versions[6] = versions[5] | {
        "execution_capture_sessions", "execution_artifacts", "execution_evidence_captures",
    }
    versions[7] = versions[6] | {"execution_veps"}
    versions[8] = versions[7] | {
        "execution_cleanup_receipts", "execution_credential_revocations", "execution_post_action_reports",
    }
    versions[9] = versions[5] | {
        "execution_capture_sessions", "execution_artifacts", "execution_evidence_captures",
        "execution_veps", "execution_cleanup_receipts", "execution_credential_revocations",
        "execution_post_action_reports", "execution_cti_feedback",
    }
    return versions


class ExecutionGatewayRepository(ExecutionAuthorizationRepository):
    """Additive atomic upgrade; preserve databases migrated by later Stage 6 controls."""
    def initialize(self) -> None:
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.execute("BEGIN IMMEDIATE")
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    versions = _execution_table_versions()
                    starting_level = 0
                    if tables:
                        if "execution_repository_meta" not in tables:
                            raise ExecutionRepositoryError("foreign execution database; no migration performed")
                        meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                        if (meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION
                                or meta["migration_level"] not in versions
                                or tables != versions[meta["migration_level"]]):
                            raise ExecutionRepositoryError("incompatible gateway repository metadata; no downgrade performed")
                        starting_level = meta["migration_level"]
                    migrations = (
                        "001_stage6_1_canonical_execution_request_contract.sql",
                        "002_stage6_2_authoritative_execution_authorization.sql",
                        "003_stage6_3_controlled_execution_gateway.sql",
                    )
                    # Apply only missing predecessor migrations. In particular,
                    # do not rewrite migration_level=9 back to 3 on a runtime DB.
                    for name in migrations[starting_level:3]:
                        sql = (Path(__file__).resolve().parents[1] / "execution_migrations" / name).read_text(encoding="utf-8")
                        statement = ""
                        for line in sql.splitlines(keepends=True):
                            statement += line
                            if sqlite3.complete_statement(statement):
                                conn.execute(statement)
                                statement = ""
                        if statement.strip():
                            raise ExecutionRepositoryError("gateway migration contains an incomplete statement")
                    if starting_level < 3:
                        conn.execute("INSERT OR IGNORE INTO execution_repository_meta VALUES (1,?,3)",
                                     (EXECUTION_REPOSITORY_SCHEMA_VERSION,))
                        conn.execute("UPDATE execution_repository_meta SET migration_level=3 WHERE singleton=1")
                self._initialized = True
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("atomic gateway migration failed") from exc

    def migration_level(self) -> int:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
        if (row is None or row["migration_level"] not in _execution_table_versions()
                or row["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION):
            raise ExecutionRepositoryError("gateway migration metadata mismatch")
        return row["migration_level"]

    def _budget_state(self, conn, authorization, *, before_sequence=None):
        req = authorization["evaluation"]["execution_request"]
        task = authorization["evaluation"]["source_binding"]["pentest_task_id"]
        budgets = {}
        where = " AND gateway_sequence<?" if before_sequence is not None else ""
        extra = [before_sequence] if before_sequence is not None else []
        for name, field, identity in (("mission", "mission_id", req["mission_id"]),
                                      ("pentest", "pentest_id", req["pentest_id"]),
                                      ("task", "pentest_task_id", task)):
            budgets[name] = conn.execute("SELECT count(*) FROM execution_gateway_submissions WHERE status=? AND " + field + "=?" + where,
                                         [ADMITTED, identity, *extra]).fetchone()[0]
        duplicate = conn.execute("SELECT 1 FROM execution_gateway_submissions WHERE status=? AND execution_id=?" + where,
                                 [ADMITTED, req["execution_id"], *extra]).fetchone() is not None
        return budgets, duplicate

    def _gateway_row(self, row: sqlite3.Row, conn) -> dict[str, Any]:
        try:
            record = json.loads(row["record_json"])
            if not verify_gateway_record(record):
                raise ExecutionRequestIntegrityError("stored gateway record failed verification")
            expected = {key: record[key] for key in ("gateway_id", "execution_id", "authorization_id", "mission_id",
                                                    "task_id", "pentest_id", "pentest_task_id", "envelope_sha256", "status")}
            expected.update({"submission_id": record["intake"]["submission_id"],
                             "idempotency_key": record["intake"]["idempotency_key"],
                             "stored_at": record["admitted_at"],
                             "record_sha256": record["integrity"]["canonical_sha256"]})
            if any(row[key] != value for key, value in expected.items()):
                raise ExecutionRequestIntegrityError("gateway index/record mismatch")
            auth_row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (record["authorization_id"],)).fetchone()
            if auth_row is None or self._authorization_row(auth_row, conn)["record"] != record["authorization_record"]:
                raise ExecutionRequestIntegrityError("gateway authorization binding is missing or changed")
            budgets, duplicate = self._budget_state(conn, record["authorization_record"], before_sequence=row["gateway_sequence"])
            if budgets != record["budget_before"] or duplicate != record["already_admitted"]:
                raise ExecutionRequestIntegrityError("gateway admission budget history is inconsistent")
            return {"gateway_id": record["gateway_id"], "gateway_sequence": row["gateway_sequence"],
                    "execution_id": record["execution_id"], "stored_at": row["stored_at"], "record": record}
        except (KeyError, ValueError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("stored gateway submission is unreadable") from exc

    def _find_intake(self, conn, intake):
        rows = conn.execute("SELECT * FROM execution_gateway_submissions WHERE submission_id=? OR idempotency_key=?",
                            (intake["submission_id"], intake["idempotency_key"])).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ExecutionRequestConflict("gateway submission identities resolve to different records")
        stored = self._gateway_row(rows[0], conn)
        if stored["record"]["intake"] != intake:
            raise ExecutionRequestConflict("gateway idempotency identity reused with different content")
        return stored

    def find_gateway_intake(self, intake):
        self.initialize()
        with closing(self._connect()) as conn:
            return self._find_intake(conn, intake)

    def append_gateway(self, intake, authorization_id: str, *, final_check: Callable[[dict[str, Any]], str]):
        """Recheck sources/expiry after write lock; reserve budgets and consume once.

        No target I/O may be performed by final_check. Independent source DBs are
        not atomically locked with this store; adapters must revalidate again.
        """
        require_id(authorization_id, "authorization_id", "eauth-")
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                old = self._find_intake(conn, intake)
                if old is not None:
                    return old, False
                row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (authorization_id,)).fetchone()
                if row is None:
                    raise ExecutionRequestIntegrityError("gateway authorization not found")
                authorization = self._authorization_row(row, conn)["record"]
                if conn.execute("SELECT 1 FROM execution_gateway_submissions WHERE authorization_id=?", (authorization_id,)).fetchone():
                    raise ExecutionRequestConflict("gateway authorization was already consumed")
                # Counts are derived from verified append-only admissions, not a caller's counters.
                for previous in conn.execute("SELECT * FROM execution_gateway_submissions WHERE mission_id=? ORDER BY gateway_sequence",
                                             (authorization["mission_id"],)).fetchall():
                    self._gateway_row(previous, conn)
                budgets, duplicate = self._budget_state(conn, authorization)
                admitted_at = final_check(authorization)
                record = make_gateway_record(intake, authorization, admitted_at=admitted_at,
                                             budget_before=budgets, already_admitted=duplicate)
                keys = ("gateway_id", "execution_id", "authorization_id", "mission_id", "task_id", "pentest_id",
                        "pentest_task_id", "envelope_sha256", "status")
                columns = ["gateway_id", "submission_id", "idempotency_key", *keys[1:], "record_sha256", "record_json", "stored_at"]
                values = [record["gateway_id"], intake["submission_id"], intake["idempotency_key"],
                          *[record[k] for k in keys[1:]], record["integrity"]["canonical_sha256"], canonical_json(record), admitted_at]
                conn.execute("INSERT INTO execution_gateway_submissions (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in values) + ")", values)
                row = conn.execute("SELECT * FROM execution_gateway_submissions WHERE gateway_id=?", (record["gateway_id"],)).fetchone()
                return self._gateway_row(row, conn), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("gateway submission could not be persisted") from exc

    def get_gateway_submission(self, gateway_id: str):
        require_id(gateway_id, "gateway_id", "egate-")
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_gateway_submissions WHERE gateway_id=?", (gateway_id,)).fetchone()
            return None if row is None else self._gateway_row(row, conn)

    def list_gateway_submissions(self, execution_id: str, limit: int = 100):
        require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExecutionRequestValidationError("gateway list limit must be 1-500")
        self.initialize()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM execution_gateway_submissions WHERE execution_id=? ORDER BY gateway_sequence LIMIT ?",
                                (execution_id, limit)).fetchall()
            return [self._gateway_row(row, conn) for row in rows]

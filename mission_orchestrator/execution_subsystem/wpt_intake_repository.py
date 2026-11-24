"""Append-only durable store for governed WPT intake records."""
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
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionSourceNotFound, canonical_json, sha256_hex,
)

WPT_INTAKE_HASH_DOMAIN = "APTS_WPT_GOVERNED_INTAKE_RECORD_V1"
WPT_RESULT_HASH_DOMAIN = "APTS_WPT_STAGE6_RESULT_RECORD_V1"
WPT_RECON_OUTBOX_HASH_DOMAIN = "APTS_WPT_RECON_HANDOFF_OUTBOX_V1"


def default_wpt_intake_path() -> Path:
    configured = os.environ.get("APTS_WPT_INTAKE_DB")
    return Path(configured).expanduser().resolve() if configured else (
        Path(__file__).resolve().parents[1] / "data" / "wpt_governed_intake.db"
    )


def _seal(core: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_hex({"hash_domain": WPT_INTAKE_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "canonicalization": "UTF8_SORTED_JSON_V1",
                                  "hash_domain": WPT_INTAKE_HASH_DOMAIN, "canonical_sha256": digest}}


def _verify(record: dict[str, Any]) -> bool:
    core = {k: v for k, v in record.items() if k != "integrity"}
    return record == _seal(core)


def _seal_result(core: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_hex({"hash_domain": WPT_RESULT_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "canonicalization": "UTF8_SORTED_JSON_V1",
                                  "hash_domain": WPT_RESULT_HASH_DOMAIN, "canonical_sha256": digest}}


def _verify_result(record: dict[str, Any]) -> bool:
    core = {k: v for k, v in record.items() if k != "integrity"}
    return record == _seal_result(core)


def _seal_handoff(core: dict[str, Any]) -> dict[str, Any]:
    digest = sha256_hex({"hash_domain": WPT_RECON_OUTBOX_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "canonicalization": "UTF8_SORTED_JSON_V1",
                                  "hash_domain": WPT_RECON_OUTBOX_HASH_DOMAIN, "canonical_sha256": digest}}


def _verify_handoff(record: dict[str, Any]) -> bool:
    core = {k: v for k, v in record.items() if k != "integrity"}
    return record == _seal_handoff(core)


class WPTIntakeRepository:
    def __init__(self, sqlite_path: str | Path | None = None) -> None:
        self.sqlite_path = Path(sqlite_path).resolve() if sqlite_path else default_wpt_intake_path()
        self._lock = RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def initialize(self) -> None:
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("""CREATE TABLE IF NOT EXISTS wpt_governed_intakes (
                        intake_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                        mission_id TEXT NOT NULL, task_id TEXT NOT NULL, record_sha256 TEXT NOT NULL,
                        record_json TEXT NOT NULL, stored_at TEXT NOT NULL)""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS wpt_intake_retirements (
                        intake_id TEXT PRIMARY KEY, record_json TEXT NOT NULL,
                        FOREIGN KEY(intake_id) REFERENCES wpt_governed_intakes(intake_id))""")
                    for operation in ('UPDATE', 'DELETE'):
                        conn.execute(f"CREATE TRIGGER IF NOT EXISTS wpt_retirement_no_{operation.lower()} BEFORE {operation} ON wpt_intake_retirements BEGIN SELECT RAISE(ABORT,'WPT retirement is append-only'); END")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_wpt_intake_mission_task ON wpt_governed_intakes(mission_id,task_id,stored_at)")
                    conn.execute("""CREATE TABLE IF NOT EXISTS wpt_stage6_results (
                        intake_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL UNIQUE,
                        attempt_id TEXT NOT NULL UNIQUE, record_sha256 TEXT NOT NULL,
                        record_json TEXT NOT NULL, stored_at TEXT NOT NULL,
                        FOREIGN KEY(intake_id) REFERENCES wpt_governed_intakes(intake_id))""")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS wpt_stage6_results_no_update BEFORE UPDATE ON wpt_stage6_results BEGIN SELECT RAISE(ABORT,'WPT Stage 6 results are append-only'); END")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS wpt_stage6_results_no_delete BEFORE DELETE ON wpt_stage6_results BEGIN SELECT RAISE(ABORT,'WPT Stage 6 results are append-only'); END")
                    conn.execute("""CREATE TABLE IF NOT EXISTS wpt_recon_handoff_outbox (
                        intake_id TEXT PRIMARY KEY, parent_recon_run_id TEXT, action_id TEXT,
                        orchestration_id TEXT NOT NULL, source_result_sha256 TEXT NOT NULL,
                        handoff_sha256 TEXT NOT NULL, handoff_json TEXT NOT NULL,
                        delivery_status TEXT NOT NULL CHECK(delivery_status IN ('PENDING','DELIVERED')),
                        attempts INTEGER NOT NULL DEFAULT 0, acknowledgement_json TEXT, acknowledgement_sha256 TEXT,
                        last_error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        FOREIGN KEY(intake_id) REFERENCES wpt_stage6_results(intake_id))""")
                    columns = {r[1]: r for r in conn.execute("PRAGMA table_info(wpt_recon_handoff_outbox)")}
                    if columns["parent_recon_run_id"][3]:
                        conn.execute("DROP TRIGGER IF EXISTS wpt_recon_handoff_no_delete")
                        conn.execute("ALTER TABLE wpt_recon_handoff_outbox RENAME TO wpt_recon_handoff_legacy")
                        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='wpt_recon_handoff_legacy'").fetchone()[0]
                        sql = sql.replace('"wpt_recon_handoff_legacy"', 'wpt_recon_handoff_outbox').replace('parent_recon_run_id TEXT NOT NULL', 'parent_recon_run_id TEXT').replace('action_id TEXT NOT NULL', 'action_id TEXT')
                        conn.execute(sql)
                        conn.execute("INSERT INTO wpt_recon_handoff_outbox SELECT * FROM wpt_recon_handoff_legacy")
                        conn.execute("DROP TABLE wpt_recon_handoff_legacy")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS wpt_recon_handoff_no_delete BEFORE DELETE ON wpt_recon_handoff_outbox BEGIN SELECT RAISE(ABORT,'WPT Recon handoff outbox is durable'); END")
            except sqlite3.Error as exc:
                raise ExecutionRequestIntegrityError("WPT intake store initialization failed") from exc
            self._initialized = True

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(row["record_json"])
            if (not _verify(record) or record["intake"]["intake_id"] != row["intake_id"]
                    or record["intake"]["idempotency_key"] != row["idempotency_key"]
                    or record["authority_snapshot"]["mission_id"] != row["mission_id"]
                    or record["authority_snapshot"]["task_id"] != row["task_id"]
                    or record["integrity"]["canonical_sha256"] != row["record_sha256"]):
                raise ExecutionRequestIntegrityError("stored WPT intake failed integrity/binding verification")
            return {"stored_at": row["stored_at"], "record": record}
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("stored WPT intake is unreadable") from exc

    def append(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not _verify(record):
            raise ExecutionRequestIntegrityError("invalid WPT intake integrity seal")
        self.initialize()
        intake = record["intake"]
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute("SELECT * FROM wpt_governed_intakes WHERE intake_id=? OR idempotency_key=?",
                                    (intake["intake_id"], intake["idempotency_key"])).fetchall()
                if rows:
                    if len(rows) != 1:
                        raise ExecutionRequestConflict("WPT intake identities resolve to different records")
                    saved = self._row(rows[0])
                    if saved["record"]["intake"] != intake:
                        raise ExecutionRequestConflict("WPT idempotency key was reused with different intake content")
                    # Idempotent retries remain bound to the original authority snapshot.
                    return saved, False
                budget = record["authority_snapshot"].get("mission_network_request_budget")
                if type(budget) is not int or budget < 1:
                    raise ExecutionRequestIntegrityError("WPT intake is missing the current authoritative request budget")
                prior_rows = conn.execute("SELECT record_json FROM wpt_governed_intakes WHERE mission_id=? AND task_id=?",
                                          (intake["mission_id"], intake["task_id"])).fetchall()
                reserved = 0
                for prior_row in prior_rows:
                    prior_record = json.loads(prior_row["record_json"])
                    if not _verify(prior_record):
                        raise ExecutionRequestIntegrityError("stored WPT intake budget reservation failed integrity verification")
                    retirement = conn.execute('SELECT record_json FROM wpt_intake_retirements WHERE intake_id=?',
                                              (prior_record['intake']['intake_id'],)).fetchone()
                    if retirement:
                        proof = json.loads(retirement[0])
                        if (not _verify(proof) or proof.get('schema_version') != 'apts-wpt-intake-retirement-v1'
                                or proof.get('intake_id') != prior_record['intake']['intake_id']
                                or proof.get('released_requests') != prior_record['authority_snapshot']['limits']['max_requests']
                                or proof['intake_sha256'] != prior_record['integrity']['canonical_sha256']):
                            raise ExecutionRequestIntegrityError('WPT retirement proof failed verification')
                    else:
                        cost = prior_record["authority_snapshot"]["limits"]["max_requests"]
                        completed = conn.execute('SELECT * FROM wpt_stage6_results WHERE intake_id=?',
                            (prior_record['intake']['intake_id'],)).fetchone()
                        if completed:
                            final = self._result_row(completed)['record']
                            source = prior_record['intake']
                            if (final.get('status') != 'VALIDATED_AND_STORED'
                                    or any(final.get(k) != source[k] for k in ('mission_id','task_id','target'))
                                    or final.get('profile_id') != prior_record['authority_snapshot']['profile_id']
                                    or final.get('action') != prior_record['authority_snapshot']['action']
                                    or final.get('evidence', {}).get('capture_status') != 'SEALED'
                                    or final.get('result', {}).get('status') != 'SUCCEEDED'):
                                raise ExecutionRequestIntegrityError('WPT budget completion binding mismatch')
                            from .wpt_budget import completed_request_cost
                            cost = completed_request_cost(final['result'].get('observation'), cost)
                        reserved += cost
                requested = record["authority_snapshot"]["limits"]["max_requests"]
                available = budget - reserved
                if available < 1:
                    raise ExecutionRequestConflict("Mission/task WPT request budget is already reserved by prior intakes")
                if requested > available:
                    adjusted = json.loads(canonical_json(record))
                    adjusted["authority_snapshot"]["limits"]["max_requests"] = available
                    record = _seal({k: v for k, v in adjusted.items() if k != "integrity"})
                stored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                conn.execute("INSERT INTO wpt_governed_intakes VALUES (?,?,?,?,?,?,?)", (
                    intake["intake_id"], intake["idempotency_key"], intake["mission_id"], intake["task_id"],
                    record["integrity"]["canonical_sha256"], canonical_json(record), stored_at))
                row = conn.execute("SELECT * FROM wpt_governed_intakes WHERE intake_id=?", (intake["intake_id"],)).fetchone()
            return self._row(row), True
        except sqlite3.IntegrityError as exc:
            raise ExecutionRequestConflict("WPT intake identity already exists") from exc
        except sqlite3.Error as exc:
            raise ExecutionRequestIntegrityError("WPT intake could not be stored") from exc

    def retire_unadmitted(self, intake_id, replacement_intake, execution_repository):
        """Release a policy-denied proposal before a revised-scope replacement.

        Runtime admission and this proof serialize on the runtime database.
        Any reservation, runtime attempt, or result prevents retirement.
        """
        from .wpt_intake_contract import normalize_wpt_intake
        replacement = normalize_wpt_intake(replacement_intake)
        replacement_id = replacement['intake_id']
        self.initialize()
        execution_repository.initialize()
        with closing(execution_repository._connect()) as runtime, runtime:
            runtime.execute('BEGIN IMMEDIATE')
            with closing(self._connect()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT * FROM wpt_governed_intakes WHERE intake_id=?', (intake_id,)).fetchone()
                if row is None:
                    raise ExecutionSourceNotFound('WPT retirement intake missing')
                original = self._row(row)['record']
                if (intake_id == replacement_id or any(original['intake'][k] != replacement[k]
                        for k in ('mission_id', 'task_id', 'target', 'profile'))):
                    raise ExecutionRequestConflict('WPT retirement requires the same logical measurement')
                prior = conn.execute('SELECT record_json FROM wpt_intake_retirements WHERE intake_id=?', (intake_id,)).fetchone()
                if prior:
                    proof = json.loads(prior[0])
                    if not _verify(proof) or proof.get('replacement_intake') != replacement:
                        raise ExecutionRequestConflict('Conflicting WPT retirement')
                    return proof
                if conn.execute('SELECT 1 FROM wpt_stage6_results WHERE intake_id=?', (intake_id,)).fetchone():
                    raise ExecutionRequestConflict('Successful WPT intake cannot be retired')
                proofs = []
                for row in runtime.execute('SELECT * FROM execution_adapter_invocations WHERE mission_id=?',
                                           (original['intake']['mission_id'],)).fetchall():
                    item = execution_repository._item(row, runtime)
                    claim = item['record']
                    request = claim['authorization_record']['evaluation']['execution_request']
                    if request.get('parameters', {}).get('source_wpt_intake_id') != intake_id:
                        continue
                    if (claim['status'] != 'BLOCKED' or item['result'] is not None
                            or claim['authorization_record']['decision'] not in ('DENY', 'REVIEW')
                            or runtime.execute('SELECT 1 FROM execution_runtime_attempts WHERE execution_id=?',
                                               (claim['execution_id'],)).fetchone()):
                        raise ExecutionRequestConflict('Retirement requires denied admission without reservation or runtime')
                    proofs.append({'invocation_id': claim['invocation_id'],
                                   'claim_sha256': claim['integrity']['canonical_sha256']})
                if not proofs:
                    raise ExecutionRequestConflict('WPT retirement has no verified admission denial')
                proof = _seal({'schema_version': 'apts-wpt-intake-retirement-v1',
                    'intake_id': intake_id, 'replacement_intake_id': replacement_id,
                    'replacement_intake': replacement,
                    'intake_sha256': original['integrity']['canonical_sha256'],
                    'released_requests': original['authority_snapshot']['limits']['max_requests'],
                    'blocked_invocations': proofs, 'terminal_attempts': [],
                    'target_network_io_performed': False,
                    'retired_at': datetime.now(timezone.utc).isoformat()})
                conn.execute('INSERT INTO wpt_intake_retirements VALUES (?,?)', (intake_id, canonical_json(proof)))
                return proof

    def retire_unused(self, intake_id, replacement_intake_id, execution_repository):
        """Retire duplicate work only with verified terminal proof of zero I/O.

        Serialize with runtime admission so a retired identity cannot race a new
        attempt. Keep immutable intake and runtime history intact.
        """
        self.initialize()
        execution_repository.initialize()
        with closing(execution_repository._connect()) as runtime, runtime:
            runtime.execute('BEGIN IMMEDIATE')
            with closing(self._connect()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                old = conn.execute('SELECT record_json FROM wpt_intake_retirements WHERE intake_id=?', (intake_id,)).fetchone()
                if old:
                    proof = json.loads(old[0])
                    if (not _verify(proof) or proof.get('intake_id') != intake_id
                            or proof.get('replacement_intake_id') != replacement_intake_id):
                        raise ExecutionRequestConflict('Conflicting WPT retirement')
                    return proof
                records = []
                for identity in (intake_id, replacement_intake_id):
                    row = conn.execute('SELECT * FROM wpt_governed_intakes WHERE intake_id=?', (identity,)).fetchone()
                    if row is None:
                        raise ExecutionSourceNotFound('WPT retirement intake missing')
                    records.append(self._row(row)['record'])
                original, replacement = records
                keys = ('mission_id', 'task_id', 'target', 'profile', 'recon_target_key', 'recon_target_sha256')
                if intake_id == replacement_intake_id or any(original['intake'].get(k) != replacement['intake'].get(k) for k in keys):
                    raise ExecutionRequestConflict('WPT retirement requires the same logical measurement')
                if conn.execute('SELECT 1 FROM wpt_stage6_results WHERE intake_id=?', (intake_id,)).fetchone():
                    raise ExecutionRequestConflict('Successful WPT intake cannot be retired')
                proofs = []
                for row in runtime.execute('SELECT * FROM execution_runtime_attempts WHERE mission_id=?', (original['intake']['mission_id'],)).fetchall():
                    item = execution_repository._runtime_item(row, runtime)
                    request = item['invocation']['record']['authorization_record']['evaluation']['execution_request']
                    if request.get('parameters', {}).get('source_wpt_intake_id') != intake_id:
                        continue
                    if not execution_repository.retryable(item):
                        raise ExecutionRequestConflict('Retirement requires proven terminal failure without target I/O')
                    proofs.append({'attempt_id': item['attempt_id'], 'head_sha256': item['head_sha256']})
                if not proofs:
                    raise ExecutionRequestConflict('WPT retirement has no verified runtime evidence')
                proof = _seal({'schema_version': 'apts-wpt-intake-retirement-v1',
                    'intake_id': intake_id, 'replacement_intake_id': replacement_intake_id,
                    'intake_sha256': original['integrity']['canonical_sha256'],
                    'released_requests': original['authority_snapshot']['limits']['max_requests'],
                    'terminal_attempts': proofs, 'target_network_io_performed': False,
                    'retired_at': datetime.now(timezone.utc).isoformat()})
                conn.execute('INSERT INTO wpt_intake_retirements VALUES (?,?)', (intake_id, canonical_json(proof)))
                return proof

    def get(self, intake_id: str) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM wpt_governed_intakes WHERE intake_id=?", (intake_id,)).fetchone()
        return None if row is None else self._row(row)

    def list_for_task(self, mission_id: str, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        self.initialize()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM wpt_governed_intakes WHERE mission_id=? AND task_id=? ORDER BY stored_at,intake_id LIMIT ?",
                                (mission_id, task_id, limit)).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _result_row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(row["record_json"])
            if (not _verify_result(record) or record["intake_id"] != row["intake_id"]
                    or record["execution_id"] != row["execution_id"]
                    or record["attempt_id"] != row["attempt_id"]
                    or record["integrity"]["canonical_sha256"] != row["record_sha256"]):
                raise ExecutionRequestIntegrityError("stored WPT Stage 6 result failed integrity/binding verification")
            return {"stored_at": row["stored_at"], "record": record}
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("stored WPT Stage 6 result is unreadable") from exc

    def append_result(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not _verify_result(record):
            raise ExecutionRequestIntegrityError("invalid WPT Stage 6 result integrity seal")
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM wpt_governed_intakes WHERE intake_id=?", (record["intake_id"],)).fetchone() is None:
                    raise ExecutionRequestIntegrityError("WPT result references an unknown intake")
                rows = conn.execute("SELECT * FROM wpt_stage6_results WHERE intake_id=? OR execution_id=? OR attempt_id=?",
                    (record["intake_id"], record["execution_id"], record["attempt_id"])).fetchall()
                if rows:
                    if len(rows) != 1:
                        raise ExecutionRequestConflict("WPT Stage 6 result identities resolve to different records")
                    saved = self._result_row(rows[0])
                    if saved["record"] != record:
                        raise ExecutionRequestConflict("WPT Stage 6 result identity was reused with different content")
                    return saved, False
                stored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                conn.execute("INSERT INTO wpt_stage6_results VALUES (?,?,?,?,?,?)", (
                    record["intake_id"], record["execution_id"], record["attempt_id"],
                    record["integrity"]["canonical_sha256"], canonical_json(record), stored_at))
                row = conn.execute("SELECT * FROM wpt_stage6_results WHERE intake_id=?", (record["intake_id"],)).fetchone()
            return self._result_row(row), True
        except sqlite3.IntegrityError as exc:
            raise ExecutionRequestConflict("WPT Stage 6 result identity already exists") from exc
        except sqlite3.Error as exc:
            raise ExecutionRequestIntegrityError("WPT Stage 6 result could not be stored") from exc

    def get_result(self, intake_id: str) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM wpt_stage6_results WHERE intake_id=?", (intake_id,)).fetchone()
        return None if row is None else self._result_row(row)

    @staticmethod
    def _handoff_row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            record = json.loads(row["handoff_json"])
            if (not _verify_handoff(record)
                    or record["intake_id"] != row["intake_id"]
                    or record["parent_recon_run_id"] != row["parent_recon_run_id"]
                    or record["action_id"] != row["action_id"]
                    or record["orchestration_id"] != row["orchestration_id"]
                    or record["source_result_sha256"] != row["source_result_sha256"]
                    or record["integrity"]["canonical_sha256"] != row["handoff_sha256"]):
                raise ExecutionRequestIntegrityError("WPT Recon handoff outbox failed integrity/binding verification")
            ack = json.loads(row["acknowledgement_json"]) if row["acknowledgement_json"] else None
            if ((ack is None) != (row["acknowledgement_sha256"] is None)
                    or (ack is not None and sha256_hex(ack) != row["acknowledgement_sha256"])):
                raise ExecutionRequestIntegrityError("Recon acknowledgement failed integrity verification")
            return {"record": record, "delivery_status": row["delivery_status"], "attempts": row["attempts"],
                    "acknowledgement": ack, "last_error_code": row["last_error_code"],
                    "created_at": row["created_at"], "updated_at": row["updated_at"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("WPT Recon handoff outbox is unreadable") from exc

    def enqueue_handoff(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not _verify_handoff(record):
            raise ExecutionRequestIntegrityError("invalid WPT Recon handoff seal")
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                result_row = conn.execute("SELECT * FROM wpt_stage6_results WHERE intake_id=?", (record["intake_id"],)).fetchone()
                if result_row is None:
                    raise ExecutionRequestIntegrityError("handoff requires a durably stored Stage 6 result")
                result = self._result_row(result_row)["record"]
                if result["integrity"]["canonical_sha256"] != record["source_result_sha256"]:
                    raise ExecutionRequestIntegrityError("handoff source result hash does not match stored Stage 6 result")
                old = conn.execute("SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?", (record["intake_id"],)).fetchone()
                if old:
                    saved = self._handoff_row(old)
                    if saved["record"] != record:
                        raise ExecutionRequestConflict("WPT intake already has a different Recon handoff binding")
                    return saved, False
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                conn.execute("INSERT INTO wpt_recon_handoff_outbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    record["intake_id"], record["parent_recon_run_id"], record["action_id"],
                    record["orchestration_id"], record["source_result_sha256"],
                    record["integrity"]["canonical_sha256"], canonical_json(record), "PENDING", 0,
                    None, None, None, now, now))
                row = conn.execute("SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?", (record["intake_id"],)).fetchone()
            return self._handoff_row(row), True
        except sqlite3.IntegrityError as exc:
            raise ExecutionRequestConflict("WPT Recon handoff outbox identity conflict") from exc
        except sqlite3.Error as exc:
            raise ExecutionRequestIntegrityError("WPT Recon handoff outbox could not be stored") from exc

    def record_handoff_attempt(self, intake_id: str, *, acknowledgement: dict[str, Any] | None = None,
                               error_code: str | None = None) -> dict[str, Any]:
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?", (intake_id,)).fetchone()
                if row is None:
                    raise ExecutionSourceNotFound("WPT Recon handoff outbox record was not found")
                saved = self._handoff_row(row)
                if saved["delivery_status"] == "DELIVERED":
                    return saved
                event = saved["record"]
                delivered = acknowledgement is not None
                if delivered and (acknowledgement.get("accepted") is not True
                        or acknowledgement.get("intake_id") != intake_id
                        or acknowledgement.get("source_result_sha256") != event["source_result_sha256"]
                        or not isinstance(acknowledgement.get("recon_run_id"), str)):
                    raise ExecutionRequestIntegrityError("Recon acknowledgement is missing required result bindings")
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                conn.execute("""UPDATE wpt_recon_handoff_outbox SET delivery_status=?,attempts=attempts+1,
                    acknowledgement_json=?,acknowledgement_sha256=?,last_error_code=?,updated_at=? WHERE intake_id=?""", (
                    "DELIVERED" if delivered else "PENDING",
                    canonical_json(acknowledgement) if delivered else None,
                    sha256_hex(acknowledgement) if delivered else None,
                    None if delivered else (error_code or "RECON_DELIVERY_FAILED"), now, intake_id))
                updated = conn.execute("SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?", (intake_id,)).fetchone()
            return self._handoff_row(updated)
        except sqlite3.Error as exc:
            raise ExecutionRequestIntegrityError("WPT Recon handoff delivery state could not be recorded") from exc

    def get_handoff(self, intake_id: str) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM wpt_recon_handoff_outbox WHERE intake_id=?", (intake_id,)).fetchone()
        return None if row is None else self._handoff_row(row)

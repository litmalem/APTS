from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from datetime import timedelta
from pathlib import Path
import sqlite3

from .adapter_contract import ADAPTER_CONTROL_VERSION, CLAIM_DOMAIN, invocation_id, verify_adapter_claim, verify_adapter_result
from .adapter_policy import compile_runtime_policy
from .authorization_contract import parse_time, utc_timestamp
from .execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceRejected, canonical_json, require_id, with_integrity,
)
from .gateway_contract import ADMITTED
from .gateway_repository import ExecutionGatewayRepository
from .request_repository import EXECUTION_REPOSITORY_SCHEMA_VERSION, ExecutionRepositoryError
from .tool_registry import registry_sha256, select_adapter


class ExecutionAdapterRepository(ExecutionGatewayRepository):
    def initialize(self):
        with self._lock:
            if self._initialized and self.sqlite_path.exists():
                return
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute("PRAGMA foreign_keys=ON")
                    conn.execute("BEGIN IMMEDIATE")
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    versions = {1: {"execution_repository_meta", "execution_requests"}}
                    versions[2] = versions[1] | {"execution_authorizations"}
                    versions[3] = versions[2] | {"execution_gateway_submissions"}
                    versions[4] = versions[3] | {"execution_adapter_invocations", "execution_adapter_results"}
                    if tables:
                        if "execution_repository_meta" not in tables:
                            raise ExecutionRepositoryError("foreign execution repository; no migration performed")
                        meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
                        if meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION or meta["migration_level"] not in versions or tables != versions[meta["migration_level"]]:
                            raise ExecutionRepositoryError("incompatible adapter repository metadata; no downgrade performed")
                    root = Path(__file__).resolve().parents[1] / "execution_migrations"
                    names = ["001_stage6_1_canonical_execution_request_contract.sql", "002_stage6_2_authoritative_execution_authorization.sql",
                             "003_stage6_3_controlled_execution_gateway.sql", "004_stage6_4_authorized_tool_adapters_sandboxing.sql"]
                    for name in names:
                        statement = ""
                        for line in (root / name).read_text(encoding="utf-8").splitlines(keepends=True):
                            statement += line
                            if sqlite3.complete_statement(statement):
                                conn.execute(statement)
                                statement = ""
                        if statement.strip():
                            raise ExecutionRepositoryError("incomplete adapter migration")
                    conn.execute("INSERT OR IGNORE INTO execution_repository_meta VALUES (1,?,4)", (EXECUTION_REPOSITORY_SCHEMA_VERSION,))
                    conn.execute("UPDATE execution_repository_meta SET migration_level=4 WHERE singleton=1")
                self._initialized = True
            except (sqlite3.Error, OSError) as exc:
                raise ExecutionRepositoryError("atomic adapter migration failed") from exc

    def migration_level(self):
        self.initialize()
        with closing(self._connect()) as conn:
            meta = conn.execute("SELECT * FROM execution_repository_meta WHERE singleton=1").fetchone()
            if meta is None or meta["schema_version"] != EXECUTION_REPOSITORY_SCHEMA_VERSION or meta["migration_level"] != 4:
                raise ExecutionRepositoryError("adapter migration metadata mismatch")
        return 4

    def _claim_row(self, row, conn):
        try:
            record = json.loads(row["record_json"])
            if not verify_adapter_claim(record):
                raise ExecutionRequestIntegrityError("adapter claim integrity mismatch")
            expected = {k: record[k] for k in ("invocation_id", "execution_id", "authorization_id", "mission_id", "pentest_id", "pentest_task_id", "gateway_id", "status", "reserved_at")}
            expected.update({"invocation_request_id": record["intake"]["invocation_request_id"], "idempotency_key": record["intake"]["idempotency_key"],
                             "credential_lease_id": None if record["controls"] is None else record["controls"]["credential_lease_id"],
                             "record_sha256": record["integrity"]["canonical_sha256"]})
            if any(row[k] != v for k, v in expected.items()):
                raise ExecutionRequestIntegrityError("adapter claim index mismatch")
            auth = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (record["authorization_id"],)).fetchone()
            if auth is None or self._authorization_row(auth, conn)["record"] != record["authorization_record"]:
                raise ExecutionRequestIntegrityError("adapter claim authorization binding mismatch")
            if record["gateway_id"]:
                gateway = conn.execute("SELECT * FROM execution_gateway_submissions WHERE gateway_id=?", (record["gateway_id"],)).fetchone()
                if gateway is None or self._gateway_row(gateway, conn)["record"]["status"] != ADMITTED or gateway["execution_id"] != record["execution_id"]:
                    raise ExecutionRequestIntegrityError("adapter gateway budget reference mismatch")
            fields = {"mission": "mission_id", "pentest": "pentest_id", "task": "pentest_task_id"}
            counts = {}
            for name, field in fields.items():
                identity = record[field]
                counts[name] = conn.execute("SELECT count(*) FROM execution_gateway_submissions WHERE status=? AND " + field + "=?", (ADMITTED, identity)).fetchone()[0]
                counts[name] += conn.execute("SELECT count(*) FROM execution_adapter_invocations WHERE status='RESERVED' AND gateway_id IS NULL AND adapter_sequence<? AND " + field + "=?", (row["adapter_sequence"], identity)).fetchone()[0]
            if counts != record["budget_before"]:
                raise ExecutionRequestIntegrityError("adapter budget history mismatch")
            if record["status"] == "RESERVED" and record["lifetime_deadlines"] != self._lifetime_deadlines(conn, record, before_sequence=row["adapter_sequence"]):
                raise ExecutionRequestIntegrityError("adapter duration budget history mismatch")
            return {"invocation_id": record["invocation_id"], "adapter_sequence": row["adapter_sequence"], "record": record}
        except (TypeError, ValueError, KeyError) as exc:
            raise ExecutionRequestIntegrityError("unreadable adapter claim") from exc

    def _result_row(self, row, conn, claim):
        try:
            record = json.loads(row["record_json"])
            if not verify_adapter_result(record):
                raise ExecutionRequestIntegrityError("adapter result integrity mismatch")
            if (record["invocation_id"] != claim["invocation_id"] or record["claim_sha256"] != claim["integrity"]["canonical_sha256"]
                    or any(record[k] != claim[k] for k in ("execution_id", "mission_id", "pentest_id", "pentest_task_id"))
                    or any(row[k] != record[k] for k in ("invocation_id", "boundary_authorization_id", "status", "completed_at"))
                    or row["record_sha256"] != record["integrity"]["canonical_sha256"]):
                raise ExecutionRequestIntegrityError("adapter result index/claim mismatch")
            if (claim["status"] != "RESERVED" or record["controls"] != claim["controls"] or record["registry_sha256"] != claim["registry_sha256"]
                    or record["adapter_id"] != claim["controls"]["adapter_id"] or record["operation"] != claim["controls"]["operation"]):
                raise ExecutionRequestIntegrityError("adapter result control binding mismatch")
            bid = record["boundary_authorization_id"]
            if bid:
                auth = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (bid,)).fetchone()
                if auth is None:
                    raise ExecutionRequestIntegrityError("missing boundary authorization")
                verified = self._authorization_row(auth, conn)["record"]
                if verified != record["boundary_authorization_record"] or verified["execution_id"] != claim["execution_id"]:
                    raise ExecutionRequestIntegrityError("boundary authorization mismatch")
                if record["semantics"]["target_network_io_performed"] and verified["decision"] != "ALLOW":
                    raise ExecutionRequestIntegrityError("target access without authoritative allow")
            elif record["boundary_authorization_record"] is not None or record["semantics"]["target_network_io_performed"]:
                raise ExecutionRequestIntegrityError("target access without boundary authorization")
            return record
        except (KeyError, ValueError, TypeError) as exc:
            raise ExecutionRequestIntegrityError("unreadable adapter result") from exc

    def _item(self, row, conn):
        item = self._claim_row(row, conn)
        result = conn.execute("SELECT * FROM execution_adapter_results WHERE invocation_id=?", (item["invocation_id"],)).fetchone()
        item["result"] = None if result is None else self._result_row(result, conn, item["record"])
        return item

    def _find_adapter(self, conn, intake):
        rows = conn.execute("SELECT * FROM execution_adapter_invocations WHERE invocation_request_id=? OR idempotency_key=?",
                            (intake["invocation_request_id"], intake["idempotency_key"])).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ExecutionRequestConflict("adapter identities resolve to different claims")
        item = self._item(rows[0], conn)
        if item["record"]["intake"] != intake:
            raise ExecutionRequestConflict("adapter idempotency content conflict")
        return item

    def find_adapter_intake(self, intake):
        self.initialize()
        with closing(self._connect()) as conn:
            return self._find_adapter(conn, intake)

    def _lifetime_deadlines(self, conn, record, *, before_sequence=None):
        fields={"mission":"mission_id","pentest":"pentest_id","task":"pentest_task_id"}
        durations=record["controls"]["source_duration_seconds"]
        deadlines={}
        for name,seconds in durations.items():
            field=fields[name]
            times=[parse_time(record["reserved_at"],"reserved_at")]
            extra=" AND adapter_sequence<?" if before_sequence is not None else ""
            args=[record[field], *([before_sequence] if before_sequence is not None else [])]
            times += [parse_time(row[0],"reserved_at") for row in conn.execute("SELECT reserved_at FROM execution_adapter_invocations WHERE status='RESERVED' AND "+field+"=?"+extra,args)]
            times += [parse_time(row[0],"admitted_at") for row in conn.execute("SELECT stored_at FROM execution_gateway_submissions WHERE status=? AND "+field+"=?",(ADMITTED,record[field]))]
            deadlines[name]=utc_timestamp(min(times)+timedelta(seconds=seconds))
        return deadlines

    def _reservation_gateway(self, gate, items, req):
        # Recon actions must pass Stage 6.3's central admission before Stage 6.4
        # can reserve an adapter. Bind the admission to this exact immutable
        # request; an admission for another execution or a stale request cannot
        # be used as a capability to reach the adapter layer.
        role = req.get("proposing_agent", {}).get("role")
        if role in {"RECONNAISSANCE", "ENUMERATION"}:
            if gate is None:
                code = "RECON_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION" if role == "RECONNAISSANCE" else "ENUMERATION_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION"
                raise ExecutionSourceRejected(code)
            if gate.get("request_sha256") != req.get("integrity", {}).get("canonical_sha256"):
                code = "RECON_GATEWAY_ADMISSION_REQUEST_BINDING_MISMATCH" if role == "RECONNAISSANCE" else "ENUMERATION_GATEWAY_ADMISSION_REQUEST_BINDING_MISMATCH"
                raise ExecutionSourceRejected(code)
        return gate

    def _check_reservation_identity(self, conn, req, items, runtime_context):
        if any(i["record"]["status"] == "RESERVED" and i["record"]["execution_id"] == req["execution_id"] for i in items):
            raise ExecutionSourceRejected("EXECUTION_ALREADY_RESERVED")

    def _reservation_active(self, item, conn):
        return item["record"]["status"] == "RESERVED" and item["result"] is None

    def _network_reservation_cost(self, item, conn):
        return item['record']['controls'].get('network_request_cost', 1)

    def _before_reservation_insert(self, conn, record, runtime_context):
        pass

    def reserve_adapter(self, intake, authorization_id, *, final_check, runtime_context=None):
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                old = self._find_adapter(conn, intake)
                if old:
                    return old, False
                auth_row = conn.execute("SELECT * FROM execution_authorizations WHERE authorization_id=?", (authorization_id,)).fetchone()
                if auth_row is None:
                    raise ExecutionRequestIntegrityError("adapter authorization missing")
                auth = self._authorization_row(auth_row, conn)["record"]
                reserved_at = final_check(auth)
                req = auth["evaluation"]["execution_request"]
                if intake["execution_id"] != req["execution_id"] or intake["envelope_sha256"] != auth["intake"]["envelope_sha256"] or intake["requested_by"] != auth["intake"]["requested_by"]:
                    raise ExecutionRequestIntegrityError("adapter intake/authorization mismatch")
                previous = conn.execute("SELECT * FROM execution_adapter_invocations WHERE mission_id=? ORDER BY adapter_sequence", (req["mission_id"],)).fetchall()
                items = [self._item(row, conn) for row in previous]
                gateways = conn.execute("SELECT * FROM execution_gateway_submissions WHERE mission_id=? ORDER BY gateway_sequence", (req["mission_id"],)).fetchall()
                gate_items = [self._gateway_row(row, conn)["record"] for row in gateways]
                gate = next((r for r in gate_items if r["execution_id"] == req["execution_id"] and r["status"] == ADMITTED), None)
                gate = self._reservation_gateway(gate, items, req)
                identity = {"mission": req["mission_id"], "pentest": req["pentest_id"], "task": auth["evaluation"]["source_binding"]["pentest_task_id"]}
                fields = {"mission": "mission_id", "pentest": "pentest_id", "task": "pentest_task_id"}
                counts = {name: sum(r["status"] == ADMITTED and r[field] == identity[name] for r in gate_items)
                          + sum(i["record"]["status"] == "RESERVED" and i["record"]["gateway_id"] is None and i["record"][field] == identity[name] for i in items)
                          for name, field in fields.items()}
                status, reasons, controls, lifetime_deadlines = "RESERVED", [], None, {}
                try:
                    adapter = select_adapter(req)
                    controls = compile_runtime_policy(auth, adapter, parse_time(reserved_at, "reserved_at"))
                    self._check_reservation_identity(conn, req, items, runtime_context)
                    if any(counts[k] + (0 if gate else 1) > controls["action_limits"][k] for k in counts):
                        raise ExecutionSourceRejected("ACTION_BUDGET_EXHAUSTED")
                    active = [i for i in items if self._reservation_active(i, conn)]
                    if len(active) >= controls["limits"]["maximum_concurrency"]:
                        raise ExecutionSourceRejected("CONCURRENCY_QUOTA_EXHAUSTED")
                    reserved = [i for i in items if i["record"]["status"] == "RESERVED"]
                    if sum(self._network_reservation_cost(i, conn) for i in reserved) + controls["network_request_cost"] > controls.get('network_request_budget', controls["limits"]["max_network_requests"]):
                        raise ExecutionSourceRejected("NETWORK_REQUEST_QUOTA_EXHAUSTED")
                    now = parse_time(reserved_at, "reserved_at")
                    recent = [i for i in reserved if (now - parse_time(i["record"]["reserved_at"], "reserved_at")).total_seconds() < controls["limits"]["rate_window_seconds"]]
                    if any(parse_time(i["record"]["reserved_at"], "reserved_at") > now for i in reserved):
                        raise ExecutionSourceRejected("ADAPTER_CLOCK_MOVED_BACKWARDS")
                    if len(recent) >= controls["limits"]["rate_requests"]:
                        raise ExecutionSourceRejected("RATE_LIMIT_EXHAUSTED")
                    lease = controls["credential_lease_id"]
                    if lease and conn.execute("SELECT 1 FROM execution_adapter_invocations WHERE credential_lease_id=? AND status='RESERVED'", (lease,)).fetchone():
                        raise ExecutionSourceRejected("CREDENTIAL_LEASE_ALREADY_CONSUMED")
                    provisional={**{field: identity[name] for name,field in fields.items()},"controls":controls,"reserved_at":reserved_at}
                    lifetime_deadlines=self._lifetime_deadlines(conn,provisional)
                    if any(now>=parse_time(value,"lifetime_deadline") for value in lifetime_deadlines.values()):
                        raise ExecutionSourceRejected("SOURCE_DURATION_BUDGET_EXHAUSTED")
                except ExecutionSourceRejected as exc:
                    status, reasons, controls, lifetime_deadlines = "BLOCKED", [str(exc)], None, {}
                record = with_integrity({"schema_version": "apts-execution-adapter-claim-v1", "control_version": ADAPTER_CONTROL_VERSION,
                    "invocation_id": invocation_id(intake), "intake": deepcopy(intake), "execution_id": req["execution_id"],
                    "envelope_sha256": intake["envelope_sha256"], "authorization_id": authorization_id, "authorization_record": auth,
                    "mission_id": req["mission_id"], "task_id": req["task_id"], "pentest_id": req["pentest_id"],
                    "pentest_task_id": identity["task"], "gateway_id": None if gate is None else gate["gateway_id"],
                    "budget_before": counts, "controls": controls, "lifetime_deadlines":lifetime_deadlines, "status": status, "reason_codes": reasons,
                    "reserved_at": reserved_at, "registry_sha256": registry_sha256()}, CLAIM_DOMAIN)
                columns = ("invocation_id", "invocation_request_id", "idempotency_key", "execution_id", "authorization_id", "mission_id", "pentest_id", "pentest_task_id", "gateway_id", "credential_lease_id", "status", "record_sha256", "record_json", "reserved_at")
                values = (record["invocation_id"], intake["invocation_request_id"], intake["idempotency_key"], req["execution_id"], authorization_id,
                          req["mission_id"], req["pentest_id"], identity["task"], record["gateway_id"], None if controls is None else controls["credential_lease_id"],
                          status, record["integrity"]["canonical_sha256"], canonical_json(record), reserved_at)
                self._before_reservation_insert(conn, record, runtime_context)
                conn.execute("INSERT INTO execution_adapter_invocations (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in values) + ")", values)
                return self._item(conn.execute("SELECT * FROM execution_adapter_invocations WHERE invocation_id=?", (record["invocation_id"],)).fetchone(), conn), True
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("adapter reservation could not be persisted") from exc

    def append_adapter_result(self, result):
        if not verify_adapter_result(result):
            raise ExecutionRequestIntegrityError("invalid adapter result")
        self.initialize()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM execution_adapter_invocations WHERE invocation_id=?", (result["invocation_id"],)).fetchone()
                if row is None:
                    raise ExecutionRequestIntegrityError("adapter claim missing")
                claim = self._claim_row(row, conn)["record"]
                old = conn.execute("SELECT * FROM execution_adapter_results WHERE invocation_id=?", (result["invocation_id"],)).fetchone()
                if old:
                    if self._result_row(old, conn, claim) != result:
                        raise ExecutionRequestConflict("different result already exists")
                    return self._item(row, conn)
                conn.execute("INSERT INTO execution_adapter_results VALUES (?,?,?,?,?,?)", (
                    result["invocation_id"], result["boundary_authorization_id"], result["status"], result["integrity"]["canonical_sha256"], canonical_json(result), result["completed_at"]))
                return self._item(row, conn)
        except sqlite3.Error as exc:
            raise ExecutionRepositoryError("adapter result persistence failed; claim remains consumed") from exc

    def get_adapter_invocation(self, identity):
        require_id(identity, "invocation_id", "toolinv-")
        self.initialize()
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM execution_adapter_invocations WHERE invocation_id=?", (identity,)).fetchone()
            return None if row is None else self._item(row, conn)

    def list_adapter_invocations(self, execution_id, limit=100):
        require_id(execution_id, "execution_id", "exec-")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExecutionRequestValidationError("adapter list limit must be 1-500")
        self.initialize()
        with closing(self._connect()) as conn:
            return [self._item(row, conn) for row in conn.execute("SELECT * FROM execution_adapter_invocations WHERE execution_id=? ORDER BY adapter_sequence LIMIT ?", (execution_id, limit)).fetchall()]

"""Execution-owned blobs and atomic evidence manifests. No filesystem artifact paths."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sys
import sqlite3

from .authorization_contract import parse_time
from .evidence_contract import (ARTIFACT_SCHEMA, EVIDENCE_CONTROL_VERSION, EVIDENCE_SCHEMA,
    KINDS, LINK_FIELDS, MAX_ARTIFACT_BYTES, MAX_ATTEMPT_BYTES, SEMANTICS,
    SESSION_DOMAIN, SESSION_SCHEMA, bytes_sha256, canonical_evidence_contract,
    seal_artifact, seal_evidence, verify_artifact, verify_evidence, verify_session)
from .execution_contract import (ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceNotFound, ExecutionSourceRejected,
    canonical_json, require_id, with_integrity)
from .runtime_contract import TERMINAL
from .execution_result_contract import build_recon_execution_result
from .runtime_repository import ExecutionRuntimeRepository
from .tool_registry import select_adapter


class ExecutionEvidenceRepository(ExecutionRuntimeRepository):
    MIGRATION_LEVEL = 6
    EXTRA_TABLES = {"execution_capture_sessions", "execution_artifacts", "execution_evidence_captures"}
    EXTRA_MIGRATIONS = ("006_stage6_6_artifact_evidence_capture.sql",)
    EXTRA_TRIGGERS = {f"{t}_no_{op}" for t in EXTRA_TABLES for op in ("update", "delete")} | {
        "execution_artifacts_closed", "execution_artifacts_quota", "execution_evidence_captures_terminal"}

    def _before_reservation_insert(self, conn, claim, runtime_context):
        super()._before_reservation_insert(conn, claim, runtime_context)
        if claim["status"] != "RESERVED":
            return
        from .runtime_contract import attempt_id
        row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?",
            (attempt_id(claim["invocation_id"]),)).fetchone()
        record = json.loads(row["record_json"])
        envelope = self._envelope(conn, record["execution_id"])
        request = envelope["execution_request"]
        source_type = envelope["intake"].get("source_type")
        is_recon = source_type == "STAGE5_2_RECON_ACTION_REQUEST"
        is_enumeration = source_type == "STAGE5_3_ENUMERATION_ACTION_PROPOSAL"
        if is_recon:
            recon_action_id = request["parameters"].get("source_action_id")
            proposal_ref = envelope["source_binding"].get("action_proposal_ref")
            if (not recon_action_id or not proposal_ref
                    or recon_action_id != envelope["intake"].get("recon_action_id")):
                raise ExecutionRequestIntegrityError("Recon evidence lineage is incomplete or mismatched")
        elif is_enumeration:
            recon_action_id = None
            proposal_ref = request["parameters"].get("source_proposal_id")
            if (not proposal_ref or proposal_ref != envelope["intake"].get("enumeration_proposal_ref")
                    or proposal_ref != envelope["source_binding"].get("action_proposal_ref")):
                raise ExecutionRequestIntegrityError("Enumeration evidence proposal lineage is incomplete or mismatched")
        else:
            recon_action_id = proposal_ref = None
        session = with_integrity({"schema_version": SESSION_SCHEMA, "control_version": EVIDENCE_CONTROL_VERSION,
            **{k:record[k] for k in LINK_FIELDS if k in record},
            "authorization_id": claim["authorization_id"], "recon_action_id": recon_action_id,
            "proposal_ref": proposal_ref, "attempt_sha256": record["integrity"]["canonical_sha256"],
            "claim_sha256": claim["integrity"]["canonical_sha256"], "envelope_sha256": claim["envelope_sha256"],
            "contract_sha256": canonical_evidence_contract()["integrity"]["canonical_sha256"],
            "enrolled_at": record["authorized_at"]}, SESSION_DOMAIN)
        conn.execute("INSERT INTO execution_capture_sessions VALUES (?,?,?)", (
            record["attempt_id"], session["integrity"]["canonical_sha256"], canonical_json(session)))
        envelope = self._envelope(conn, record["execution_id"])
        adapter = select_adapter(envelope["execution_request"])
        self._insert_artifact(conn, session, "TOOL_IDENTITY", {"adapter": adapter.definition(),
            "registry_sha256": claim["registry_sha256"], "fixed_worker": "sandbox_worker.py",
            "worker_source_sha256": bytes_sha256(Path(__file__).with_name("sandbox_worker.py").read_bytes()),
            "python_version": list(sys.version_info[:3]),
            "shell": False, "arbitrary_command": False}, record["authorized_at"])
        req = envelope["execution_request"]
        # Free-text expected evidence is retained in its immutable request, not copied to output blobs.
        self._insert_artifact(conn, session, "ACTION_PARAMETERS", {
            "action": req["action"], "target": req["target"], "operation": adapter.operation,
            "recon_action_id": session["recon_action_id"], "proposal_ref": session["proposal_ref"],
            "authorization_id": session["authorization_id"],
            "parameters": {next(k for k in ("source_action_id", "source_proposal_id", "validation_task_id", "source_wpt_intake_id") if k in req["parameters"]):
                next(req["parameters"][k] for k in ("source_action_id", "source_proposal_id", "validation_task_id", "source_wpt_intake_id") if k in req["parameters"]),
                "estimated_impact": req["parameters"]["estimated_impact"],
                "expected_evidence_sha256": bytes_sha256(canonical_json(req["parameters"]["expected_evidence"]).encode())},
            "parameters_sha256": bytes_sha256(canonical_json(req["parameters"]).encode()),
            "credential_lease_id": claim["controls"]["credential_lease_id"],
            "authorization_header_retained": False, "controls": claim["controls"],
            "envelope_sha256": claim["envelope_sha256"]}, record["authorized_at"])
        self._insert_artifact(conn, session, "BEFORE_STATE", {"runtime_state": "AUTHORIZED",
            "authorization_id": claim["authorization_id"],
            "current_context_sha256": bytes_sha256(canonical_json(claim["authorization_record"]["evaluation"]["current_context"]).encode()),
            "target_state_measured": False}, record["authorized_at"])

    def _envelope(self, conn, execution_id):
        row = conn.execute("SELECT * FROM execution_requests WHERE execution_id=?", (execution_id,)).fetchone()
        if row is None:
            raise ExecutionRequestIntegrityError("capture execution request missing")
        return self._row(row)["envelope"]

    def _session(self, conn, record):
        row = conn.execute("SELECT * FROM execution_capture_sessions WHERE attempt_id=?", (record["attempt_id"],)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["record_json"])
            first_event = conn.execute("SELECT record_json FROM execution_runtime_events WHERE attempt_id=? AND event_sequence=1",
                                       (record["attempt_id"],)).fetchone()
            if first_event is None:
                raise ExecutionRequestIntegrityError("capture authorization event missing")
            authorization_id = json.loads(first_event["record_json"])["data"].get("authorization_id")
            envelope = self._envelope(conn, record["execution_id"])
            source_type = envelope["intake"].get("source_type")
            is_recon = source_type == "STAGE5_2_RECON_ACTION_REQUEST"
            is_enumeration = source_type == "STAGE5_3_ENUMERATION_ACTION_PROPOSAL"
            request = envelope["execution_request"]
            expected_action_id = request["parameters"].get("source_action_id") if is_recon else None
            expected_proposal_ref = envelope["source_binding"].get("action_proposal_ref") if (is_recon or is_enumeration) else None
            if (not verify_session(value) or row["record_sha256"] != value["integrity"]["canonical_sha256"]
                or row["attempt_id"] != value["attempt_id"]
                or any(value[k] != record[k] for k in LINK_FIELDS if k in record)
                or value["authorization_id"] != authorization_id
                or value["recon_action_id"] != expected_action_id
                or value["proposal_ref"] != expected_proposal_ref
                or value["attempt_sha256"] != record["integrity"]["canonical_sha256"]
                or value["claim_sha256"] != record["claim_sha256"]
                or value["envelope_sha256"] != record["runtime_intake"]["envelope_sha256"]
                or value["enrolled_at"] != record["authorized_at"]):
                raise ExecutionRequestIntegrityError("capture session binding mismatch")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("invalid capture session") from exc

    def _insert_artifact(self, conn, session, kind, value, at, *, captured_sha256=None,
                         captured_size_bytes=None, redacted=False, complete=True):
        if kind not in KINDS:
            raise ExecutionRequestValidationError("unsupported artifact kind")
        payload = canonical_json(value).encode("utf-8")
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise ExecutionSourceRejected("ARTIFACT_BYTE_QUOTA_EXCEEDED")
        if parse_time(at, "captured_at") < parse_time(session["enrolled_at"], "enrolled_at"):
            raise ExecutionRequestIntegrityError("capture clock moved backwards")
        record = seal_artifact({"schema_version": ARTIFACT_SCHEMA, "control_version": EVIDENCE_CONTROL_VERSION,
            **{k:session[k] for k in LINK_FIELDS}, "session_sha256": session["integrity"]["canonical_sha256"],
            "kind": kind, "media_type": "application/json", "producer": "SERVER_RUNTIME",
            "privacy_policy": "METADATA_ALLOWLIST_V1", "captured_at": at,
            "content_sha256": bytes_sha256(payload), "size_bytes": len(payload),
            "captured_sha256": captured_sha256 if captured_sha256 is not None else bytes_sha256(payload),
            "captured_size_bytes": captured_size_bytes if captured_size_bytes is not None else len(payload),
            "redacted": redacted, "capture_complete": complete})
        if not verify_artifact(record, payload):
            raise ExecutionRequestIntegrityError("invalid artifact descriptor")
        old = conn.execute("SELECT * FROM execution_artifacts WHERE attempt_id=? AND kind=?",
                           (session["attempt_id"], kind)).fetchone()
        if old:
            if self._artifact_row(old, session) != (record, payload):
                raise ExecutionRequestConflict("artifact slot already contains different capture")
            return record
        total = conn.execute("SELECT coalesce(sum(length(payload)),0) FROM execution_artifacts WHERE attempt_id=?",
                             (session["attempt_id"],)).fetchone()[0]
        if total + len(payload) > MAX_ATTEMPT_BYTES:
            raise ExecutionSourceRejected("ATTEMPT_ARTIFACT_QUOTA_EXCEEDED")
        conn.execute("INSERT INTO execution_artifacts VALUES (?,?,?,?,?,?,?)", (
            record["artifact_id"], session["attempt_id"], kind, sqlite3.Binary(payload),
            record["content_sha256"], record["integrity"]["canonical_sha256"], canonical_json(record)))
        return record

    def store_capture(self, identity, owner_id, kind, value, at, **metadata):
        require_id(identity, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("capture attempt not found")
            item = self._runtime_item(row, conn)
            if item["state"] in TERMINAL or item["record"]["owner_id"] != owner_id:
                raise ExecutionSourceRejected("CAPTURE_REQUIRES_ACTIVE_EXACT_RUNTIME_OWNER")
            if kind not in {"STDOUT", "STDERR", "TARGET_RESPONSE", "NETWORK_OBSERVATION"}:
                raise ExecutionSourceRejected("SERVER_CAPTURE_KIND_RESERVED")
            session = self._session(conn, item["record"])
            if session is None:
                raise ExecutionSourceRejected("ATTEMPT_NOT_ENROLLED_FOR_CAPTURE")
            return self._insert_artifact(conn, session, kind, value, at, **metadata)

    def _artifact_row(self, row, session):
        try:
            value = json.loads(row["record_json"])
            payload = bytes(row["payload"])
            if (not verify_artifact(value, payload) or any(value[k] != session[k] for k in LINK_FIELDS)
                or value["session_sha256"] != session["integrity"]["canonical_sha256"]
                or any(row[k] != value[k] for k in ("artifact_id", "attempt_id", "kind", "content_sha256"))
                or row["record_sha256"] != value["integrity"]["canonical_sha256"]
                or parse_time(value["captured_at"], "captured_at") < parse_time(session["enrolled_at"], "enrolled_at")
                or canonical_json(json.loads(payload)).encode("utf-8") != payload):
                raise ExecutionRequestIntegrityError("artifact blob/index/lineage mismatch")
            return value, payload
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("unreadable artifact") from exc

    def _artifacts(self, conn, session):
        items = [self._artifact_row(r, session) for r in conn.execute(
            "SELECT * FROM execution_artifacts WHERE attempt_id=? ORDER BY kind", (session["attempt_id"],))]
        if len(items) > len(KINDS) or sum(len(p) for _,p in items) > MAX_ATTEMPT_BYTES:
            raise ExecutionRequestIntegrityError("capture artifact quota mismatch")
        return items

    @staticmethod
    def _coverage(item, artifacts):
        by_kind = {a["kind"]:a for a in artifacts}
        recovery = item["target_io_uncertain"]
        result = item["invocation"]["result"]
        coverage = {}
        for kind in KINDS:
            if kind in by_kind:
                coverage[kind] = "PRESENT" if by_kind[kind]["capture_complete"] else "PARTIAL"
            elif recovery:
                coverage[kind] = "NOT_DURABLY_CAPTURED_BEFORE_CRASH"
            elif kind in {"STDOUT", "STDERR"} and result and not result["semantics"]["tool_invocation_performed"]:
                coverage[kind] = "NOT_PRODUCED"
            elif kind in {"NETWORK_OBSERVATION", "TARGET_RESPONSE"} and result and not result["semantics"]["target_network_io_performed"]:
                coverage[kind] = "NO_TARGET_IO"
            else:
                coverage[kind] = "NOT_OBSERVED"
        coverage.update({"SCREENSHOTS": "NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS",
            "TARGET_BEFORE_STATE": "NOT_MEASURED", "TARGET_AFTER_STATE": "NOT_MEASURED"})
        return coverage

    def _core(self, item, session, artifacts):
        event = item["events"][-1]
        result = item["invocation"]["result"]
        coverage = self._coverage(item, artifacts)
        partial = any(v in {"PARTIAL", "NOT_OBSERVED", "NOT_DURABLY_CAPTURED_BEFORE_CRASH"} for v in coverage.values())
        return {"schema_version": EVIDENCE_SCHEMA, "control_version": EVIDENCE_CONTROL_VERSION,
            **{k:session[k] for k in LINK_FIELDS}, "session_sha256": session["integrity"]["canonical_sha256"],
            "attempt_sha256": item["record"]["integrity"]["canonical_sha256"],
            "claim_sha256": item["record"]["claim_sha256"], "envelope_sha256": session["envelope_sha256"],
            "state": item["state"], "sealed_at": event["occurred_at"],
            "authorized_at": item["record"]["authorized_at"],
            "started_at": next((e["occurred_at"] for e in item["events"] if e["event_type"] == "RUNNING"), None),
            "runtime_event_count": len(item["events"]), "terminal_event_id": event["event_id"],
            "terminal_event_sha256": item["head_sha256"],
            "adapter_result_sha256": None if result is None else result["integrity"]["canonical_sha256"],
            "boundary_authorization_id": None if result is None else result["boundary_authorization_id"],
            "capture_status": "RECOVERED_PARTIAL" if item["target_io_uncertain"] else "PARTIAL" if partial else "CAPTURED",
            "target_io_uncertain": item["target_io_uncertain"], "coverage": coverage,
            "artifacts": artifacts, "stored_bytes": sum(a["size_bytes"] for a in artifacts),
            "semantics": dict(SEMANTICS)}

    def _insert_event(self, conn, record, previous, state, event_type, at, data, actor):
        if event_type == "AUTHORIZED":
            data = {**data, "evidence_contract_sha256": canonical_evidence_contract()["integrity"]["canonical_sha256"]}
        event = super()._insert_event(conn, record, previous, state, event_type, at, data, actor)
        if state not in TERMINAL:
            return event
        session = self._session(conn, record)
        if session is None:
            return event
        row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (record["attempt_id"],)).fetchone()
        item = super()._runtime_item(row, conn)
        result = item["invocation"]["result"]
        if result is not None:
            self._insert_artifact(conn, session, "RESULT", {"status": result["status"],
                "adapter_result_sha256": result["integrity"]["canonical_sha256"], "observation": result["observation"],
                "semantics": result["semantics"]}, at)
        self._insert_artifact(conn, session, "AFTER_STATE", {"runtime_state": state,
            "terminal_event_sha256": event["integrity"]["canonical_sha256"],
            "target_io_uncertain": item["target_io_uncertain"], "target_state_measured": False}, at)
        artifacts = [a for a,_ in self._artifacts(conn, session)]
        value = seal_evidence(self._core(item, session, artifacts))
        if not verify_evidence(value):
            raise ExecutionRequestIntegrityError("invalid evidence manifest")
        conn.execute("INSERT INTO execution_evidence_captures VALUES (?,?,?,?,?)", (
            value["evidence_id"], record["attempt_id"], event["event_id"],
            value["integrity"]["canonical_sha256"], canonical_json(value)))
        return event

    def _verified_capture(self, conn, item):
        session = self._session(conn, item["record"])
        marker = item["events"][0]["data"].get("evidence_contract_sha256")
        if session is None:
            if marker is not None:
                raise ExecutionRequestIntegrityError("enrolled attempt missing capture session")
            return None, []
        if marker != session["contract_sha256"]:
            raise ExecutionRequestIntegrityError("capture enrollment event mismatch")
        pairs = self._artifacts(conn, session)
        artifacts = [a for a,_ in pairs]
        content = {a["kind"]:(a, json.loads(p)) for a,p in pairs}
        if not {"TOOL_IDENTITY", "ACTION_PARAMETERS", "BEFORE_STATE"} <= set(content):
            raise ExecutionRequestIntegrityError("mandatory admission capture missing")
        result = item["invocation"]["result"]
        if result and result["observation"]:
            from .evidence_contract import observation_network_binding
            observation = observation_network_binding(result["observation"])
            for kind in ("NETWORK_OBSERVATION", "TARGET_RESPONSE"):
                if kind not in content:
                    raise ExecutionRequestIntegrityError("observed result missing target capture")
                descriptor, payload = content[kind]
                if any(payload[k] != observation[k] for k in ("response_bytes", "response_sha256")):
                    raise ExecutionRequestIntegrityError("result/target capture mismatch")
                if kind == "TARGET_RESPONSE" and (descriptor["captured_sha256"] != observation["response_sha256"]
                    or descriptor["captured_size_bytes"] != observation["response_bytes"]):
                    raise ExecutionRequestIntegrityError("target response original digest mismatch")
        if item["state"] == "SUCCEEDED" and set(content) != set(KINDS):
            raise ExecutionRequestIntegrityError("successful execution missing capture kinds")
        row = conn.execute("SELECT * FROM execution_evidence_captures WHERE attempt_id=?", (item["attempt_id"],)).fetchone()
        if item["state"] not in TERMINAL:
            if row is not None:
                raise ExecutionRequestIntegrityError("manifest sealed without terminal attempt")
            return None, artifacts
        if row is None:
            raise ExecutionRequestIntegrityError("terminal attempt missing atomic evidence manifest")
        try:
            value = json.loads(row["record_json"])
            if (not verify_evidence(value) or value != seal_evidence(self._core(item, session, artifacts))
                or any(row[k] != value[k] for k in ("evidence_id", "attempt_id", "terminal_event_id"))
                or row["record_sha256"] != value["integrity"]["canonical_sha256"]
                or any(parse_time(a["captured_at"], "captured_at") > parse_time(value["sealed_at"], "sealed_at") for a in artifacts)):
                raise ExecutionRequestIntegrityError("evidence manifest/terminal/lineage mismatch")
            return value, artifacts
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionRequestIntegrityError("unreadable evidence manifest") from exc

    def _runtime_item(self, row, conn):
        item = super()._runtime_item(row, conn)
        manifest, artifacts = self._verified_capture(conn, item)
        item["evidence_capture"] = {"status": manifest["capture_status"] if manifest else
            "CAPTURING" if item["events"][0]["data"].get("evidence_contract_sha256") else "LEGACY_NOT_CAPTURED",
            "evidence_id": None if manifest is None else manifest["evidence_id"],
            "manifest_sha256": None if manifest is None else manifest["integrity"]["canonical_sha256"],
            "artifact_count": len(artifacts), "sealed": manifest is not None}
        return item

    def get_evidence(self, identity):
        require_id(identity, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (identity,)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("evidence attempt not found")
            item = self._runtime_item(row, conn)
            manifest, artifacts = self._verified_capture(conn, item)
            return {**item["evidence_capture"], "attempt_id": identity, "manifest": manifest,
                "artifacts": artifacts, "historical_record": True, "read_only": True,
                "target_network_io_performed": False, **SEMANTICS}

    def get_wpt_result_snapshot(self, execution_id, attempt_identity):
        """Return a WPT result only from the verified Stage 6 runtime/evidence ledger."""
        from .execution_contract import require_id
        require_id(execution_id, "execution_id", "exec-")
        require_id(attempt_identity, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT * FROM execution_runtime_attempts WHERE attempt_id=? AND execution_id=?",
                (attempt_identity, execution_id),
            ).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("Stage 6 WPT attempt not found")
            item = self._runtime_item(row, conn)
            envelope = self._envelope(conn, execution_id)
            manifest, artifacts = self._verified_capture(conn, item)
            request = envelope["execution_request"]
            return {
                "attempt_id": item["attempt_id"], "execution_id": item["record"]["execution_id"],
                "mission_id": item["record"]["mission_id"], "task_id": item["record"]["task_id"],
                "runtime_state": item["state"], "action": request["action"],
                "target": request["target"], "parameters": request["parameters"],
                "runtime_result": item["invocation"]["result"],
                "evidence": None if manifest is None else {
                    "sealed": True, "evidence_id": manifest["evidence_id"],
                    "manifest_sha256": manifest["integrity"]["canonical_sha256"],
                    "manifest": manifest,
                    "artifacts": artifacts,
                },
                "source": "VERIFIED_STAGE6_RUNTIME_AND_STAGE6_6_EVIDENCE_LEDGER",
            }

    def get_recon_action_attempts(self, action_id):
        """Return verified runtime attempts for one persisted Recon Action Request."""
        require_id(action_id, "recon_action_id", "rareq-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                "SELECT a.*, s.record_json AS capture_session_json FROM execution_runtime_attempts a "
                "JOIN execution_capture_sessions s ON s.attempt_id=a.attempt_id "
                "ORDER BY a.execution_id, a.attempt_number, a.rowid"
            ).fetchall()
            results = []
            for row in rows:
                try:
                    indexed_session = json.loads(row["capture_session_json"])
                except (TypeError, ValueError) as exc:
                    raise ExecutionRequestIntegrityError("unreadable Recon runtime capture session") from exc
                if indexed_session.get("recon_action_id") != action_id:
                    continue
                item = self._runtime_item(row, conn)
                session = self._session(conn, item["record"])
                if session is None or session["recon_action_id"] != action_id:
                    raise ExecutionRequestIntegrityError("Recon Action Request runtime session binding mismatch")
                envelope = self._envelope(conn, item["record"]["execution_id"])
                intake = envelope["intake"]
                if intake.get("source_type") != "STAGE5_2_RECON_ACTION_REQUEST" or intake.get("recon_action_id") != action_id:
                    raise ExecutionRequestIntegrityError("runtime attempt is not bound to the requested Recon Action Request")
                proposal_ref = envelope["source_binding"].get("action_proposal_ref")
                if proposal_ref != session["proposal_ref"]:
                    raise ExecutionRequestIntegrityError("Recon proposal lineage binding mismatch")
                manifest, _ = self._verified_capture(conn, item)
                try:
                    result = build_recon_execution_result(action_id=action_id,
                        proposal_ref=proposal_ref,
                        orchestration_id=envelope["execution_request"]["proposing_agent"]["orchestration_id"],
                        item=item, manifest=manifest)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ExecutionRequestIntegrityError("invalid durable Recon ExecutionResult") from exc
                results.append(result)
            return results

    def get_enumeration_proposal_attempts(self, proposal_ref):
        """Return verified Stage-6 attempts for one exact Stage-5.3 proposal."""
        require_id(proposal_ref, "enumeration_proposal_ref", "actp-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            rows = conn.execute(
                "SELECT a.*, s.record_json AS capture_session_json FROM execution_runtime_attempts a "
                "JOIN execution_capture_sessions s ON s.attempt_id=a.attempt_id "
                "ORDER BY a.execution_id, a.attempt_number, a.rowid").fetchall()
            results = []
            for row in rows:
                try:
                    indexed_session = json.loads(row["capture_session_json"])
                except (TypeError, ValueError) as exc:
                    raise ExecutionRequestIntegrityError("unreadable Enumeration runtime capture session") from exc
                if indexed_session.get("proposal_ref") != proposal_ref:
                    continue
                item = self._runtime_item(row, conn)
                session = self._session(conn, item["record"])
                envelope = self._envelope(conn, item["record"]["execution_id"])
                intake = envelope["intake"]
                if (session is None or session["proposal_ref"] != proposal_ref
                        or intake.get("source_type") != "STAGE5_3_ENUMERATION_ACTION_PROPOSAL"
                        or intake.get("enumeration_proposal_ref") != proposal_ref
                        or envelope["execution_request"]["parameters"].get("source_proposal_id") != proposal_ref):
                    raise ExecutionRequestIntegrityError("runtime attempt is not bound to the requested Enumeration proposal")
                manifest, _ = self._verified_capture(conn, item)
                from .execution_result_contract import build_enumeration_execution_result
                try:
                    result = build_enumeration_execution_result(proposal_ref=proposal_ref,
                        orchestration_id=envelope["execution_request"]["proposing_agent"]["orchestration_id"],
                        item=item, manifest=manifest)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ExecutionRequestIntegrityError("invalid durable Enumeration ExecutionResult") from exc
                results.append(result)
            return results

    def get_artifact(self, identity, attempt_id):
        require_id(identity, "artifact_id", "xartifact-")
        require_id(attempt_id, "attempt_id", "xattempt-")
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM execution_artifacts WHERE artifact_id=? AND attempt_id=?", (identity, attempt_id)).fetchone()
            if row is None:
                raise ExecutionSourceNotFound("artifact not found in exact attempt")
            attempt = conn.execute("SELECT * FROM execution_runtime_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            item = self._runtime_item(attempt, conn)
            return self._artifact_row(row, self._session(conn, item["record"]))

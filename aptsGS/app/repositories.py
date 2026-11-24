from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from .db import Db, to_json
from .utils import safe_json_loads
from .approval_auth import ApprovalAccessError


class GovernanceRepository:
    def __init__(self, db: Optional[Db] = None):
        self.db = db or Db()

    # ---------- Policy ----------
    def get_policy_set(self, policy_set_id: str) -> Optional[dict]:
        return self.db.fetch_one(
            """
            SELECT policy_set_id, name, version, status, default_effect,
                   effective_from, effective_until, description
              FROM gov_policy_sets
             WHERE policy_set_id=%(policy_set_id)s
            """,
            {"policy_set_id": policy_set_id},
        )

    # ---------- Scope / RoE ----------
    def insert_scope_contract(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_scope_contracts
                (scope_contract_id, mission_id, name, status, policy_set_id, version,
                 valid_from, valid_until, created_by, approved_by, approved_at,
                 metadata_json, contract_hash, created_at, updated_at)
            VALUES
                (%(scope_contract_id)s, %(mission_id)s, %(name)s, %(status)s,
                 %(policy_set_id)s, %(version)s, %(valid_from)s, %(valid_until)s,
                 %(created_by)s, %(approved_by)s, %(approved_at)s,
                 %(metadata_json)s, %(contract_hash)s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def insert_scope_targets(self, rows: Iterable[dict]) -> None:
        self.db.execute_many(
            """
            INSERT INTO gov_scope_targets
                (scope_target_id, scope_contract_id, target_type, target_value,
                 normalized_value, environment, allowed, notes, created_at)
            VALUES
                (%(scope_target_id)s, %(scope_contract_id)s, %(target_type)s,
                 %(target_value)s, %(normalized_value)s, %(environment)s,
                 %(allowed)s, %(notes)s, CURRENT_TIMESTAMP)
            """,
            rows,
        )

    def insert_scope_sources(self, rows: Iterable[dict]) -> None:
        self.db.execute_many(
            """
            INSERT INTO gov_scope_sources
                (scope_source_id, scope_contract_id, source_id, source_type,
                 allowed, constraints_json, created_at)
            VALUES
                (%(scope_source_id)s, %(scope_contract_id)s, %(source_id)s,
                 %(source_type)s, %(allowed)s, %(constraints_json)s, CURRENT_TIMESTAMP)
            """,
            rows,
        )

    def insert_action_constraints(self, rows: Iterable[dict]) -> None:
        self.db.execute_many(
            """
            INSERT INTO gov_scope_action_constraints
                (constraint_id, scope_contract_id, action_class, action_name,
                 effect, max_risk_level, requires_approval, constraints_json, created_at)
            VALUES
                (%(constraint_id)s, %(scope_contract_id)s, %(action_class)s,
                 %(action_name)s, %(effect)s, %(max_risk_level)s,
                 %(requires_approval)s, %(constraints_json)s, CURRENT_TIMESTAMP)
            """,
            rows,
        )

    def get_scope_contract(self, scope_contract_id: str) -> Optional[dict]:
        row = self.db.fetch_one(
            """
            SELECT * FROM gov_scope_contracts
             WHERE scope_contract_id=%(scope_contract_id)s
            """,
            {"scope_contract_id": scope_contract_id},
        )
        if not row:
            return None
        row["metadata"] = safe_json_loads(row.pop("metadata_json", None), {}) or {}
        row["targets"] = self.db.fetch_all(
            "SELECT * FROM gov_scope_targets WHERE scope_contract_id=%(id)s ORDER BY id",
            {"id": scope_contract_id},
        )
        sources = self.db.fetch_all(
            "SELECT * FROM gov_scope_sources WHERE scope_contract_id=%(id)s ORDER BY id",
            {"id": scope_contract_id},
        )
        for src in sources:
            src["constraints"] = safe_json_loads(src.pop("constraints_json", None), {}) or {}
        row["sources"] = sources
        constraints = self.db.fetch_all(
            "SELECT * FROM gov_scope_action_constraints WHERE scope_contract_id=%(id)s ORDER BY id",
            {"id": scope_contract_id},
        )
        for item in constraints:
            # MariaDB/MySQL drivers expose TINYINT(1) as int. Normalize the
            # REST-facing value to a JSON boolean while rejecting corrupt data.
            requires_approval = item.get("requires_approval")
            if type(requires_approval) is bool:
                pass
            elif type(requires_approval) is int and requires_approval in (0, 1):
                item["requires_approval"] = bool(requires_approval)
            else:
                raise ValueError(
                    "gov_scope_action_constraints.requires_approval must be 0 or 1"
                )
            item["constraints"] = safe_json_loads(item.pop("constraints_json", None), {}) or {}
        row["action_constraints"] = constraints
        return row

    def find_active_scope_for_mission(self, mission_id: str) -> Optional[dict]:
        row = self.db.fetch_one(
            """
            SELECT scope_contract_id
              FROM gov_scope_contracts
             WHERE mission_id=%(mission_id)s
               AND status='ACTIVE'
               AND (valid_from IS NULL OR valid_from <= CURRENT_TIMESTAMP)
               AND (valid_until IS NULL OR valid_until >= CURRENT_TIMESTAMP)
             ORDER BY version DESC, created_at DESC
             LIMIT 1
            """,
            {"mission_id": mission_id},
        )
        return self.get_scope_contract(row["scope_contract_id"]) if row else None

    def find_action_constraint(self, scope_contract_id: str, action_class: str, action_name: str) -> Optional[dict]:
        row = self.db.fetch_one(
            """
            SELECT *
              FROM gov_scope_action_constraints
             WHERE scope_contract_id=%(scope_contract_id)s
               AND action_class=%(action_class)s
               AND action_name IN (%(action_name)s, '*')
             ORDER BY (action_name=%(action_name)s) DESC, id ASC
             LIMIT 1
            """,
            {
                "scope_contract_id": scope_contract_id,
                "action_class": action_class,
                "action_name": action_name,
            },
        )
        if row:
            row["constraints"] = safe_json_loads(row.pop("constraints_json", None), {}) or {}
        return row

    # ---------- Authorization ----------
    def insert_authorization_request(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_authorization_requests
                (request_id, mission_id, scope_contract_id, subject_component,
                 action_class, action_name, resource_type, resource_value,
                 context_json, evidence_refs_json, requested_by, request_status,
                 requested_at, updated_at)
            VALUES
                (%(request_id)s, %(mission_id)s, %(scope_contract_id)s,
                 %(subject_component)s, %(action_class)s, %(action_name)s,
                 %(resource_type)s, %(resource_value)s, %(context_json)s,
                 %(evidence_refs_json)s, %(requested_by)s, 'EVALUATING',
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def get_authorization_request(self, request_id: str) -> Optional[dict]:
        row = self.db.fetch_one(
            "SELECT * FROM gov_authorization_requests WHERE request_id=%(id)s",
            {"id": request_id},
        )
        if row:
            row["context"] = safe_json_loads(row.pop("context_json", None), {}) or {}
            row["evidence_refs"] = safe_json_loads(row.pop("evidence_refs_json", None), []) or []
        return row

    def update_authorization_status(self, request_id: str, status: str) -> None:
        self.db.execute(
            """
            UPDATE gov_authorization_requests
               SET request_status=%(status)s, updated_at=CURRENT_TIMESTAMP
             WHERE request_id=%(request_id)s
            """,
            {"request_id": request_id, "status": status},
        )

    def insert_risk_assessment(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_risk_assessments
                (assessment_id, request_id, mission_id, risk_score, risk_level,
                 factors_json, created_at)
            VALUES
                (%(assessment_id)s, %(request_id)s, %(mission_id)s,
                 %(risk_score)s, %(risk_level)s, %(factors_json)s, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def insert_policy_decision(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_policy_decisions
                (decision_id, request_id, mission_id, policy_set_id, policy_version,
                 scope_contract_id, scope_version, decision, reason_codes_json,
                 constraints_json, requires_human_approval, approval_request_id,
                 valid_from, valid_until, decision_hash, supersedes_decision_id,
                 decision_status, created_at, updated_at)
            VALUES
                (%(decision_id)s, %(request_id)s, %(mission_id)s, %(policy_set_id)s,
                 %(policy_version)s, %(scope_contract_id)s, %(scope_version)s,
                 %(decision)s, %(reason_codes_json)s, %(constraints_json)s,
                 %(requires_human_approval)s, %(approval_request_id)s,
                 %(valid_from)s, %(valid_until)s, %(decision_hash)s,
                 %(supersedes_decision_id)s, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def get_policy_decision(self, decision_id: str) -> Optional[dict]:
        row = self.db.fetch_one(
            "SELECT * FROM gov_policy_decisions WHERE decision_id=%(id)s",
            {"id": decision_id},
        )
        if row:
            row["reason_codes"] = safe_json_loads(row.pop("reason_codes_json", None), []) or []
            row["constraints"] = safe_json_loads(row.pop("constraints_json", None), {}) or {}
        return row

    def revoke_policy_decision(self, decision_id: str) -> bool:
        affected = self.db.execute(
            """
            UPDATE gov_policy_decisions
               SET decision_status='REVOKED', updated_at=CURRENT_TIMESTAMP
             WHERE decision_id=%(id)s AND decision_status='ACTIVE'
            """,
            {"id": decision_id},
        )
        return affected > 0

    def expire_policy_decision(self, decision_id: str) -> bool:
        affected = self.db.execute(
            """
            UPDATE gov_policy_decisions
               SET decision_status='EXPIRED', updated_at=CURRENT_TIMESTAMP
             WHERE decision_id=%(id)s AND decision_status='ACTIVE'
            """,
            {"id": decision_id},
        )
        return affected > 0

    # ---------- Approval ----------
    def insert_approval_request(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_approval_requests
                (approval_request_id, authorization_request_id, mission_id,
                 risk_level, reason, required_approver_role, status,
                 expires_at, created_at, updated_at)
            VALUES
                (%(approval_request_id)s, %(authorization_request_id)s, %(mission_id)s,
                 %(risk_level)s, %(reason)s, %(required_approver_role)s,
                 'PENDING', %(expires_at)s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def get_approval_request(self, approval_request_id: str) -> Optional[dict]:
        return self.db.fetch_one(
            "SELECT * FROM gov_approval_requests WHERE approval_request_id=%(id)s",
            {"id": approval_request_id},
        )

    def insert_approval_decision(self, row: dict) -> None:
        # The conditional update locks and consumes the pending request exactly
        # once. Insert and all subsequent decision/audit/outbox writes share the
        # outer approval transaction; any failure rolls the whole operation back.
        with self.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE gov_approval_requests
                       SET status=%(status)s, updated_at=CURRENT_TIMESTAMP
                     WHERE approval_request_id=%(approval_request_id)s
                       AND status='PENDING'
                       AND expires_at IS NOT NULL AND expires_at > UTC_TIMESTAMP()
                       AND required_approver_role=%(approver_role)s
                       AND authorization_request_id=%(authorization_request_id)s
                       AND mission_id=%(mission_id)s
                    """,
                    {**row, "status": "APPROVED" if row["decision"] == "APPROVE" else "DENIED"},
                )
                if cur.rowcount != 1:
                    raise ApprovalAccessError("APPROVAL_NO_LONGER_PENDING_OR_VALID", 409)
                cur.execute("""
                INSERT INTO gov_approval_decisions
                    (approval_decision_id, approval_request_id, approver_id,
                     approver_role, decision, reason, decision_hash, decided_at)
                VALUES
                    (%(approval_decision_id)s, %(approval_request_id)s,
                     %(approver_id)s, %(approver_role)s, %(decision)s,
                     %(reason)s, %(decision_hash)s, CURRENT_TIMESTAMP)
                """,
                row)

    def approval_transaction(self):
        return self.db.connect()


    def list_compliance_obligations(self, policy_set_id: str, action_class: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT obligation_id, policy_set_id, action_class, obligation_type,
                   description, mandatory, config_json
              FROM gov_compliance_obligations
             WHERE policy_set_id=%(policy_set_id)s
               AND enabled=1
               AND (action_class IS NULL OR action_class=%(action_class)s)
             ORDER BY mandatory DESC, id ASC
            """,
            {"policy_set_id": policy_set_id, "action_class": action_class},
        )
        for row in rows:
            row["config"] = safe_json_loads(row.pop("config_json", None), {}) or {}
        return rows

    def active_mission_ids(self) -> list[str]:
        rows = self.db.fetch_all(
            """
            SELECT DISTINCT mission_id
              FROM gov_scope_contracts
             WHERE status='ACTIVE'
               AND (valid_from IS NULL OR valid_from <= CURRENT_TIMESTAMP)
               AND (valid_until IS NULL OR valid_until >= CURRENT_TIMESTAMP)
             ORDER BY mission_id
            """
        )
        return [str(row["mission_id"]) for row in rows if row.get("mission_id")]

    # ---------- Emergency stop ----------
    def get_emergency_state(self) -> dict:
        row = self.db.fetch_one("SELECT * FROM gov_emergency_state WHERE singleton_id=1")
        return row or {"active": 1, "version": 0, "reason": "STATE_NOT_INITIALIZED"}

    def set_emergency_state(self, *, active: bool, actor_id: str, reason: str, metadata: dict, action_id: str) -> dict:
        state = self.get_emergency_state()
        new_version = int(state.get("version") or 0) + 1
        statements = [
            (
                """
                INSERT INTO gov_emergency_actions
                    (action_id, action_type, actor_id, reason, metadata_json, created_at)
                VALUES
                    (%(action_id)s, %(action_type)s, %(actor_id)s, %(reason)s,
                     %(metadata_json)s, CURRENT_TIMESTAMP)
                """,
                {
                    "action_id": action_id,
                    "action_type": "ACTIVATE" if active else "RELEASE",
                    "actor_id": actor_id,
                    "reason": reason,
                    "metadata_json": to_json(metadata),
                },
            ),
            (
                """
                UPDATE gov_emergency_state
                   SET active=%(active)s,
                       reason=%(reason)s,
                       version=%(version)s,
                       activated_by=CASE WHEN %(active)s=1 THEN %(actor_id)s ELSE activated_by END,
                       activated_at=CASE WHEN %(active)s=1 THEN CURRENT_TIMESTAMP ELSE activated_at END,
                       released_by=CASE WHEN %(active)s=0 THEN %(actor_id)s ELSE NULL END,
                       released_at=CASE WHEN %(active)s=0 THEN CURRENT_TIMESTAMP ELSE NULL END,
                       updated_at=CURRENT_TIMESTAMP
                 WHERE singleton_id=1
                """,
                {
                    "active": 1 if active else 0,
                    "reason": reason,
                    "version": new_version,
                    "actor_id": actor_id,
                },
            ),
        ]
        self.db.execute_transaction(statements)
        return self.get_emergency_state()

    # ---------- Autonomy-level grants (AL-025) ----------
    def ensure_authorization_level_schema(self) -> None:
        """Idempotent DDL for the level grant + transition stores (sqlite/mysql portable)."""
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS gov_authorization_level_grant (
                grant_id VARCHAR(128) PRIMARY KEY,
                mission_id VARCHAR(128) NOT NULL,
                scope_contract_id VARCHAR(128) NOT NULL,
                authorized_level INTEGER NOT NULL,
                status VARCHAR(32) NOT NULL,
                valid_from VARCHAR(40) NOT NULL,
                valid_until VARCHAR(40) NOT NULL,
                requires_reauthorization INTEGER NOT NULL DEFAULT 0,
                grant_sha256 VARCHAR(64) NOT NULL,
                predecessor_grant_sha256 VARCHAR(64),
                grant_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS gov_authorization_level_transition (
                transition_id VARCHAR(128) PRIMARY KEY,
                transition_type VARCHAR(32) NOT NULL,
                mission_id VARCHAR(128) NOT NULL,
                scope_contract_id VARCHAR(128) NOT NULL,
                from_grant_sha256 VARCHAR(64),
                to_grant_sha256 VARCHAR(64),
                from_level INTEGER,
                to_level INTEGER,
                signal VARCHAR(64),
                approver VARCHAR(128),
                transition_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def save_level_grant(self, grant: dict) -> dict:
        """Insert a grant, superseding any prior ACTIVE grant for the same mission+scope."""
        self.ensure_authorization_level_schema()
        statements = [
            (
                """
                UPDATE gov_authorization_level_grant
                   SET status='SUPERSEDED'
                 WHERE mission_id=%(mission_id)s
                   AND scope_contract_id=%(scope_contract_id)s
                   AND status='ACTIVE'
                """,
                {"mission_id": grant["mission_id"], "scope_contract_id": grant["scope_contract_id"]},
            ),
            (
                """
                INSERT INTO gov_authorization_level_grant
                    (grant_id, mission_id, scope_contract_id, authorized_level, status,
                     valid_from, valid_until, requires_reauthorization, grant_sha256,
                     predecessor_grant_sha256, grant_json)
                VALUES
                    (%(grant_id)s, %(mission_id)s, %(scope_contract_id)s, %(authorized_level)s,
                     %(status)s, %(valid_from)s, %(valid_until)s, %(requires_reauthorization)s,
                     %(grant_sha256)s, %(predecessor_grant_sha256)s, %(grant_json)s)
                """,
                {
                    "grant_id": grant["grant_id"],
                    "mission_id": grant["mission_id"],
                    "scope_contract_id": grant["scope_contract_id"],
                    "authorized_level": int(grant["authorized_level"]),
                    "status": grant["status"],
                    "valid_from": grant["valid_from"],
                    "valid_until": grant["valid_until"],
                    "requires_reauthorization": 1 if grant["requires_reauthorization"] else 0,
                    "grant_sha256": grant["integrity"]["canonical_sha256"],
                    "predecessor_grant_sha256": grant.get("predecessor_grant_sha256"),
                    "grant_json": to_json(grant),
                },
            ),
        ]
        self.db.execute_transaction(statements)
        return grant

    def get_active_level_grant(self, *, mission_id: str, scope_contract_id: str) -> Optional[dict]:
        """Return the sealed ACTIVE grant for a mission+scope, or None."""
        row = self.db.fetch_one(
            """
            SELECT grant_json FROM gov_authorization_level_grant
             WHERE mission_id=%(mission_id)s
               AND scope_contract_id=%(scope_contract_id)s
               AND status='ACTIVE'
             ORDER BY created_at DESC
             LIMIT 1
            """,
            {"mission_id": mission_id, "scope_contract_id": scope_contract_id},
        )
        return safe_json_loads(row["grant_json"]) if row else None

    def save_level_transition(self, transition: dict, *, transition_id: str,
                              mission_id: str, scope_contract_id: str) -> dict:
        self.ensure_authorization_level_schema()
        self.db.execute(
            """
            INSERT INTO gov_authorization_level_transition
                (transition_id, transition_type, mission_id, scope_contract_id,
                 from_grant_sha256, to_grant_sha256, from_level, to_level,
                 signal, approver, transition_json)
            VALUES
                (%(transition_id)s, %(transition_type)s, %(mission_id)s, %(scope_contract_id)s,
                 %(from_grant_sha256)s, %(to_grant_sha256)s, %(from_level)s, %(to_level)s,
                 %(signal)s, %(approver)s, %(transition_json)s)
            """,
            {
                "transition_id": transition_id,
                "transition_type": transition["transition_type"],
                "mission_id": mission_id,
                "scope_contract_id": scope_contract_id,
                "from_grant_sha256": transition["from_grant_sha256"],
                "to_grant_sha256": transition["to_grant_sha256"],
                "from_level": transition["from_level"],
                "to_level": transition["to_level"],
                "signal": transition["signal"],
                "approver": transition["approver"],
                "transition_json": to_json(transition),
            },
        )
        return transition

    # ---------- Oversight monitoring (HO L4 / A3) ----------
    def ensure_monitoring_schema(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS gov_monitoring_heartbeat (
                singleton_id INTEGER PRIMARY KEY,
                last_sample_at VARCHAR(40),
                sample_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def read_monitoring_heartbeat(self) -> Optional[dict]:
        self.ensure_monitoring_schema()
        return self.db.fetch_one(
            "SELECT last_sample_at, sample_count FROM gov_monitoring_heartbeat WHERE singleton_id=1"
        )

    def touch_monitoring_heartbeat(self, *, sampled_at: str) -> None:
        self.ensure_monitoring_schema()
        existing = self.db.fetch_one(
            "SELECT sample_count FROM gov_monitoring_heartbeat WHERE singleton_id=1"
        )
        if existing is None:
            self.db.execute(
                """
                INSERT INTO gov_monitoring_heartbeat (singleton_id, last_sample_at, sample_count)
                VALUES (1, %(sampled_at)s, 1)
                """,
                {"sampled_at": sampled_at},
            )
        else:
            self.db.execute(
                """
                UPDATE gov_monitoring_heartbeat
                   SET last_sample_at=%(sampled_at)s, sample_count=sample_count+1
                 WHERE singleton_id=1
                """,
                {"sampled_at": sampled_at},
            )

    def _count_since(self, sql: str, since: str, extra: Optional[dict] = None) -> int:
        params = {"since": since, **(extra or {})}
        row = self.db.fetch_one(sql, params)
        return int((row or {}).get("n") or 0)

    def monitoring_window(self, *, since: str) -> dict:
        """Aggregate governance activity since ``since`` (a 'YYYY-MM-DD HH:MM:SS' UTC
        string, format-matched to CURRENT_TIMESTAMP) into the monitoring-window shape
        that `oversight_attestation.monitoring_alerts` consumes."""
        total = self._count_since(
            "SELECT COUNT(*) AS n FROM gov_policy_decisions WHERE created_at >= %(since)s", since)
        ineligible = self._count_since(
            "SELECT COUNT(*) AS n FROM gov_policy_decisions WHERE created_at >= %(since)s AND decision=%(d)s",
            since, {"d": "DENY"})
        emergency = self._count_since(
            "SELECT COUNT(*) AS n FROM gov_emergency_actions WHERE created_at >= %(since)s AND action_type=%(t)s",
            since, {"t": "ACTIVATE"})
        downgrades = 0
        try:
            downgrades = self._count_since(
                "SELECT COUNT(*) AS n FROM gov_authorization_level_transition WHERE created_at >= %(since)s AND transition_type=%(t)s",
                since, {"t": "DOWNGRADE"})
        except Exception:
            downgrades = 0  # table not provisioned yet
        return {
            "total_decisions": total,
            "ineligible": ineligible,
            "emergency_stops": emergency,
            "downgrades": downgrades,
            "integrity_failures": self.audit_chain_breaks(since=since),
        }

    def audit_chain_breaks(self, *, since: Optional[str] = None) -> int:
        """Count hash-chain linkage breaks (previous_hash != prior record_hash) among
        audit rows, scoped to >= ``since`` when given. A cheap tamper/gap signal."""
        sql = "SELECT previous_hash, record_hash FROM gov_audit_log"
        params: dict = {}
        if since is not None:
            sql += " WHERE created_at >= %(since)s"
            params = {"since": since}
        sql += " ORDER BY id ASC"
        try:
            rows = self.db.fetch_all(sql, params)
        except Exception:
            return 0
        breaks = 0
        for prev, cur in zip(rows, rows[1:]):
            if cur.get("previous_hash") != prev.get("record_hash"):
                breaks += 1
        return breaks

    # ---------- Audit ----------
    def last_audit_hash(self) -> Optional[str]:
        row = self.db.fetch_one("SELECT record_hash FROM gov_audit_log ORDER BY id DESC LIMIT 1")
        return row.get("record_hash") if row else None

    def insert_audit(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_audit_log
                (audit_id, event_type, actor_id, mission_id, subject_type, subject_id,
                 payload_json, previous_hash, record_hash, created_at)
            VALUES
                (%(audit_id)s, %(event_type)s, %(actor_id)s, %(mission_id)s,
                 %(subject_type)s, %(subject_id)s, %(payload_json)s,
                 %(previous_hash)s, %(record_hash)s, CURRENT_TIMESTAMP)
            """,
            row,
        )

    # ---------- Event outbox ----------
    def insert_outbox(self, row: dict) -> None:
        self.db.execute(
            """
            INSERT INTO gov_event_outbox
                (event_id, mission_id, event_type, source_component, severity,
                 payload_json, delivery_status, attempt_count, created_at, updated_at)
            VALUES
                (%(event_id)s, %(mission_id)s, %(event_type)s, %(source_component)s,
                 %(severity)s, %(payload_json)s, 'PENDING', 0,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            row,
        )

    def pending_outbox(self, limit: int = 50) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT * FROM gov_event_outbox
             WHERE delivery_status IN ('PENDING','FAILED')
               AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP)
             ORDER BY id ASC LIMIT %(limit)s
            """,
            {"limit": max(1, min(int(limit), 500))},
        )
        for row in rows:
            row["payload"] = safe_json_loads(row.pop("payload_json", None), {}) or {}
        return rows

    def outbox_stats(self) -> dict:
        row = self.db.fetch_one(
            """
            SELECT COUNT(*) AS total,
                   SUM(delivery_status='PENDING') AS pending,
                   SUM(delivery_status='FAILED') AS failed,
                   SUM(delivery_status='DELIVERED') AS delivered,
                   MAX(delivered_at) AS last_delivered_at,
                   MAX(updated_at) AS last_updated_at
              FROM gov_event_outbox
            """
        ) or {}
        return {
            "total": int(row.get("total") or 0),
            "pending": int(row.get("pending") or 0),
            "failed": int(row.get("failed") or 0),
            "delivered": int(row.get("delivered") or 0),
            "last_delivered_at": row.get("last_delivered_at"),
            "last_updated_at": row.get("last_updated_at"),
        }

    def recent_outbox(self, limit: int = 25) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT event_id, mission_id, event_type, source_component, severity,
                   delivery_status, attempt_count, last_error, next_attempt_at,
                   delivered_at, created_at, updated_at
              FROM gov_event_outbox
             ORDER BY id DESC
             LIMIT %(limit)s
            """,
            {"limit": max(1, min(int(limit), 200))},
        )
        return rows

    def mark_outbox_delivered(self, event_id: str) -> None:
        self.db.execute(
            """
            UPDATE gov_event_outbox
               SET delivery_status='DELIVERED', attempt_count=attempt_count+1,
                   delivered_at=CURRENT_TIMESTAMP, last_error=NULL,
                   updated_at=CURRENT_TIMESTAMP
             WHERE event_id=%(id)s
            """,
            {"id": event_id},
        )

    # ---------- Stage 2.9.4 Governance correlation read model ----------
    def mission_scope_contracts(self, mission_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM gov_scope_contracts
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        for row in rows:
            row["metadata"] = safe_json_loads(row.pop("metadata_json", None), {}) or {}
        return rows

    def mission_authorization_requests(self, mission_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM gov_authorization_requests
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        for row in rows:
            row["context"] = safe_json_loads(row.pop("context_json", None), {}) or {}
            row["evidence_refs"] = safe_json_loads(row.pop("evidence_refs_json", None), []) or []
        return rows

    def mission_policy_decisions(self, mission_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM gov_policy_decisions
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        for row in rows:
            row["reason_codes"] = safe_json_loads(row.pop("reason_codes_json", None), []) or []
            row["constraints"] = safe_json_loads(row.pop("constraints_json", None), {}) or {}
        return rows

    def mission_outbox_events(self, mission_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM gov_event_outbox
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        for row in rows:
            row["payload"] = safe_json_loads(row.pop("payload_json", None), {}) or {}
        return rows

    def mission_audit_records(self, mission_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM gov_audit_log
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        for row in rows:
            row["payload"] = safe_json_loads(row.pop("payload_json", None), {}) or {}
        return rows

    def mark_outbox_failed(self, event_id: str, error: str) -> None:
        self.db.execute(
            """
            UPDATE gov_event_outbox
               SET delivery_status='FAILED', attempt_count=attempt_count+1,
                   last_error=%(error)s,
                   next_attempt_at=DATE_ADD(CURRENT_TIMESTAMP,
                       INTERVAL LEAST(60, POW(2, LEAST(attempt_count, 5))) SECOND),
                   updated_at=CURRENT_TIMESTAMP
             WHERE event_id=%(id)s
            """,
            {"id": event_id, "error": error[:2000]},
        )

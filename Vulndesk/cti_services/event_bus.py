from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from .common import new_id, safe_json_loads, utcnow_iso
from .db_adapter import DbAdapter, to_json


EventHandler = Callable[[Dict[str, Any]], None]

CTI_EVENT_SCHEMA_V1 = "cti-event-v1"
CTI_EVENT_SCHEMA_V2 = "cti-event-v2"


@dataclass
class CtiEvent:
    """Canonical CTI event envelope.

    Stage 2.8.1-2.8.3 lineage semantics:
    - event_id: unique local event identity.
    - trace_id: stable end-to-end proposal/task lineage root.
    - causation_event_id: immediate parent event inside VulnDesk.
    - upstream_event_id: external subsystem event identity (for example gevent-*).
    - proposal_id/task_id/policy_decision_id/authorization_request_id/revalidation_id:
      first-class business identifiers used for deterministic reconstruction.

    The v2 fields are intentionally optional so historical v1 events remain truthful
    rather than receiving synthetic lineage during migration.
    """

    event_id: str
    event_type: str
    source_component: str
    mission_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    severity: str = "INFO"
    state_version: Optional[int] = None
    plan_version: Optional[int] = None
    policy_version: Optional[str] = None
    evidence_ref: Optional[str] = None

    event_schema_version: str = CTI_EVENT_SCHEMA_V2
    trace_id: Optional[str] = None
    causation_event_id: Optional[str] = None
    upstream_event_id: Optional[str] = None
    proposal_id: Optional[str] = None
    task_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    authorization_request_id: Optional[str] = None
    revalidation_id: Optional[str] = None

    created_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_schema_version": self.event_schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source_component": self.source_component,
            "mission_id": self.mission_id,
            "trace_id": self.trace_id,
            "causation_event_id": self.causation_event_id,
            "upstream_event_id": self.upstream_event_id,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "policy_decision_id": self.policy_decision_id,
            "authorization_request_id": self.authorization_request_id,
            "revalidation_id": self.revalidation_id,
            "payload": dict(self.payload or {}),
            "severity": self.severity,
            "state_version": self.state_version,
            "plan_version": self.plan_version,
            "policy_version": self.policy_version,
            "evidence_ref": self.evidence_ref,
            "created_at": self.created_at,
        }


class CtiEventBus:
    """Typed in-process CTI event bus with durable event/audit persistence.

    Publication and dispatch remain separated.  Stage 2.8 adds a schema-aware
    v2 event envelope while preserving pre-migration operation.  If migration 07
    has not yet been installed, persistence falls back to the historical v1
    column set; the in-memory event still retains its v2 fields.
    """

    WILDCARD = "*"

    _V2_COLUMNS = (
        "event_schema_version",
        "trace_id",
        "causation_event_id",
        "upstream_event_id",
        "proposal_id",
        "task_id",
        "policy_decision_id",
        "authorization_request_id",
        "revalidation_id",
    )

    def __init__(self, db: Optional[DbAdapter] = None):
        self.db = db or DbAdapter()
        self._queue: Deque[Dict[str, Any]] = deque()
        self._subscribers: Dict[str, List[Tuple[str, EventHandler]]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        subscriber_id: Optional[str] = None,
    ) -> str:
        normalized = str(event_type or self.WILDCARD).upper()
        sid = subscriber_id or getattr(handler, "__name__", "subscriber")
        with self._lock:
            pair = (sid, handler)
            if pair not in self._subscribers[normalized]:
                self._subscribers[normalized].append(pair)
        return sid

    def unsubscribe(self, subscriber_id: str, event_type: Optional[str] = None) -> None:
        with self._lock:
            keys = [str(event_type).upper()] if event_type else list(self._subscribers.keys())
            for key in keys:
                self._subscribers[key] = [
                    pair for pair in self._subscribers.get(key, []) if pair[0] != subscriber_id
                ]

    def publish(
        self,
        event_type: str,
        *,
        source_component: str,
        mission_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        severity: str = "INFO",
        state_version: Optional[int] = None,
        plan_version: Optional[int] = None,
        policy_version: Optional[str] = None,
        evidence_ref: Optional[str] = None,
        event_id: Optional[str] = None,
        event_schema_version: str = CTI_EVENT_SCHEMA_V2,
        trace_id: Optional[str] = None,
        causation_event_id: Optional[str] = None,
        upstream_event_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        authorization_request_id: Optional[str] = None,
        revalidation_id: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        event = CtiEvent(
            event_id=event_id or new_id("event"),
            event_type=str(event_type or "UNKNOWN").upper(),
            source_component=str(source_component or "UNKNOWN"),
            mission_id=mission_id,
            payload=dict(payload or {}),
            severity=str(severity or "INFO").upper(),
            state_version=state_version,
            plan_version=plan_version,
            policy_version=policy_version,
            evidence_ref=evidence_ref,
            event_schema_version=str(event_schema_version or CTI_EVENT_SCHEMA_V2),
            trace_id=trace_id,
            causation_event_id=causation_event_id,
            upstream_event_id=upstream_event_id,
            proposal_id=proposal_id,
            task_id=task_id,
            policy_decision_id=policy_decision_id,
            authorization_request_id=authorization_request_id,
            revalidation_id=revalidation_id,
        ).as_dict()
        if persist:
            self._persist_event(event)
        with self._lock:
            self._queue.append(event)
        return event

    def enqueue_existing(self, event: Dict[str, Any]) -> None:
        normalized = dict(event)
        normalized["event_type"] = str(normalized.get("event_type") or "UNKNOWN").upper()
        normalized.setdefault("event_id", new_id("event"))
        normalized.setdefault("event_schema_version", CTI_EVENT_SCHEMA_V1)
        normalized.setdefault("trace_id", None)
        normalized.setdefault("causation_event_id", None)
        normalized.setdefault("upstream_event_id", None)
        normalized.setdefault("proposal_id", None)
        normalized.setdefault("task_id", None)
        normalized.setdefault("policy_decision_id", None)
        normalized.setdefault("authorization_request_id", None)
        normalized.setdefault("revalidation_id", None)
        normalized.setdefault("payload", {})
        normalized.setdefault("created_at", utcnow_iso())
        with self._lock:
            self._queue.append(normalized)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def pop(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()

    def subscribers_for(self, event_type: str) -> List[Tuple[str, EventHandler]]:
        normalized = str(event_type or "UNKNOWN").upper()
        with self._lock:
            return list(self._subscribers.get(normalized, [])) + list(
                self._subscribers.get(self.WILDCARD, [])
            )

    def mark_delivery(
        self,
        event: Dict[str, Any],
        subscriber_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        try:
            if not self.db.table_exists("cti_event_deliveries"):
                return
            self.db.execute(
                """
                INSERT INTO cti_event_deliveries
                    (delivery_id, event_id, mission_id, subscriber_id, delivery_status,
                     attempt_count, last_error, delivered_at, created_at)
                VALUES
                    (%(delivery_id)s, %(event_id)s, %(mission_id)s, %(subscriber_id)s,
                     %(delivery_status)s, 1, %(last_error)s,
                     CASE WHEN %(delivery_status)s='DELIVERED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                     CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    delivery_status=VALUES(delivery_status),
                    attempt_count=attempt_count+1,
                    last_error=VALUES(last_error),
                    delivered_at=CASE WHEN VALUES(delivery_status)='DELIVERED' THEN CURRENT_TIMESTAMP ELSE delivered_at END,
                    updated_at=CURRENT_TIMESTAMP
                """,
                {
                    "delivery_id": f"{event.get('event_id')}:{subscriber_id}",
                    "event_id": event.get("event_id"),
                    "mission_id": event.get("mission_id"),
                    "subscriber_id": subscriber_id,
                    "delivery_status": status,
                    "last_error": error,
                },
            )
        except Exception:
            return

    def _v2_schema_available(self) -> bool:
        try:
            if not self.db.table_exists("cti_events"):
                return False
            columns = self.db.columns("cti_events")
            return all(column in columns for column in self._V2_COLUMNS)
        except Exception:
            return False

    def recent_events(self, mission_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.db.table_exists("cti_events"):
            return []

        v2 = self._v2_schema_available()
        if v2:
            select_sql = """
                SELECT event_id, event_schema_version, mission_id, event_type,
                       source_component, severity, trace_id, causation_event_id,
                       upstream_event_id, proposal_id, task_id, policy_decision_id,
                       authorization_request_id, revalidation_id, payload_json,
                       state_version, plan_version, policy_version, evidence_ref, created_at
                  FROM cti_events
                 WHERE mission_id=%(mission_id)s
                 ORDER BY id DESC
                 LIMIT %(limit)s
            """
        else:
            select_sql = """
                SELECT event_id, mission_id, event_type, source_component, severity,
                       payload_json, state_version, plan_version, policy_version,
                       evidence_ref, created_at
                  FROM cti_events
                 WHERE mission_id=%(mission_id)s
                 ORDER BY id DESC
                 LIMIT %(limit)s
            """

        rows = self.db.fetch_all(
            select_sql,
            {"mission_id": mission_id, "limit": max(1, min(int(limit), 1000))},
        )
        for row in rows:
            row["payload"] = safe_json_loads(row.pop("payload_json", None), default={}) or {}
            row.setdefault("event_schema_version", CTI_EVENT_SCHEMA_V1)
            row.setdefault("trace_id", None)
            row.setdefault("causation_event_id", None)
            row.setdefault("upstream_event_id", None)
            row.setdefault("proposal_id", None)
            row.setdefault("task_id", None)
            row.setdefault("policy_decision_id", None)
            row.setdefault("authorization_request_id", None)
            row.setdefault("revalidation_id", None)
        return rows

    def _persist_event(self, event: Dict[str, Any]) -> None:
        try:
            if not self.db.table_exists("cti_events"):
                return

            if self._v2_schema_available():
                self.db.execute(
                    """
                    INSERT INTO cti_events
                        (event_id, event_schema_version, mission_id, event_type,
                         source_component, severity, trace_id, causation_event_id,
                         upstream_event_id, proposal_id, task_id, policy_decision_id,
                         authorization_request_id, revalidation_id, payload_json,
                         state_version, plan_version, policy_version, evidence_ref, created_at)
                    VALUES
                        (%(event_id)s, %(event_schema_version)s, %(mission_id)s,
                         %(event_type)s, %(source_component)s, %(severity)s,
                         %(trace_id)s, %(causation_event_id)s, %(upstream_event_id)s,
                         %(proposal_id)s, %(task_id)s, %(policy_decision_id)s,
                         %(authorization_request_id)s, %(revalidation_id)s,
                         %(payload_json)s, %(state_version)s, %(plan_version)s,
                         %(policy_version)s, %(evidence_ref)s, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                        event_schema_version=VALUES(event_schema_version),
                        severity=VALUES(severity), payload_json=VALUES(payload_json),
                        trace_id=VALUES(trace_id), causation_event_id=VALUES(causation_event_id),
                        upstream_event_id=VALUES(upstream_event_id), proposal_id=VALUES(proposal_id),
                        task_id=VALUES(task_id), policy_decision_id=VALUES(policy_decision_id),
                        authorization_request_id=VALUES(authorization_request_id),
                        revalidation_id=VALUES(revalidation_id),
                        state_version=VALUES(state_version), plan_version=VALUES(plan_version),
                        policy_version=VALUES(policy_version), evidence_ref=VALUES(evidence_ref)
                    """,
                    {
                        "event_id": event.get("event_id"),
                        "event_schema_version": event.get("event_schema_version") or CTI_EVENT_SCHEMA_V2,
                        "mission_id": event.get("mission_id"),
                        "event_type": event.get("event_type"),
                        "source_component": event.get("source_component"),
                        "severity": event.get("severity") or "INFO",
                        "trace_id": event.get("trace_id"),
                        "causation_event_id": event.get("causation_event_id"),
                        "upstream_event_id": event.get("upstream_event_id"),
                        "proposal_id": event.get("proposal_id"),
                        "task_id": event.get("task_id"),
                        "policy_decision_id": event.get("policy_decision_id"),
                        "authorization_request_id": event.get("authorization_request_id"),
                        "revalidation_id": event.get("revalidation_id"),
                        "payload_json": to_json(event.get("payload") or {}),
                        "state_version": event.get("state_version"),
                        "plan_version": event.get("plan_version"),
                        "policy_version": event.get("policy_version"),
                        "evidence_ref": event.get("evidence_ref"),
                    },
                )
                return

            # Backward-compatible persistence before migration 07.
            self.db.execute(
                """
                INSERT INTO cti_events
                    (event_id, mission_id, event_type, source_component, severity,
                     payload_json, state_version, plan_version, policy_version,
                     evidence_ref, created_at)
                VALUES
                    (%(event_id)s, %(mission_id)s, %(event_type)s, %(source_component)s,
                     %(severity)s, %(payload_json)s, %(state_version)s, %(plan_version)s,
                     %(policy_version)s, %(evidence_ref)s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    severity=VALUES(severity), payload_json=VALUES(payload_json),
                    state_version=VALUES(state_version), plan_version=VALUES(plan_version),
                    policy_version=VALUES(policy_version), evidence_ref=VALUES(evidence_ref)
                """,
                {
                    "event_id": event.get("event_id"),
                    "mission_id": event.get("mission_id"),
                    "event_type": event.get("event_type"),
                    "source_component": event.get("source_component"),
                    "severity": event.get("severity") or "INFO",
                    "payload_json": to_json(event.get("payload") or {}),
                    "state_version": event.get("state_version"),
                    "plan_version": event.get("plan_version"),
                    "policy_version": event.get("policy_version"),
                    "evidence_ref": event.get("evidence_ref"),
                },
            )
        except Exception:
            # The in-memory bus remains available if event persistence is down.
            return

from __future__ import annotations

from typing import Any, Dict, Optional

from .common import new_id, utcnow_iso
from .db_adapter import DbAdapter, to_json


class AuditStore:
    """Append-only decision/event audit helper.

    The design requires trigger/input snapshots, versions, candidate alternatives,
    selected result, evidence references and downstream event pointers to be
    reconstructable.  This helper intentionally does not mutate prior audit rows.
    """

    TABLE = "cti_audit_log"

    def __init__(self, db: Optional[DbAdapter] = None):
        self.db = db or DbAdapter()

    def append(
        self,
        *,
        mission_id: Optional[str],
        component_id: str,
        event_type: str,
        reason_code: Optional[str] = None,
        input_snapshot: Any = None,
        candidate_alternatives: Any = None,
        selected_output: Any = None,
        evidence_refs: Any = None,
        versions: Any = None,
        upstream_event_ref: Optional[str] = None,
        downstream_event_ref: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        audit_id = new_id("audit")
        try:
            if self.db.table_exists(self.TABLE):
                self.db.execute(
                    f"""
                    INSERT INTO {self.TABLE}
                        (audit_id, mission_id, component_id, event_type, reason_code,
                         input_snapshot_json, candidate_alternatives_json, selected_output_json,
                         evidence_refs_json, versions_json, upstream_event_ref, downstream_event_ref, trace_id, created_at)
                    VALUES
                        (%(audit_id)s, %(mission_id)s, %(component_id)s, %(event_type)s, %(reason_code)s,
                         %(input_snapshot_json)s, %(candidate_alternatives_json)s, %(selected_output_json)s,
                         %(evidence_refs_json)s, %(versions_json)s, %(upstream_event_ref)s, %(downstream_event_ref)s, %(trace_id)s,
                         CURRENT_TIMESTAMP)
                    """,
                    {
                        "audit_id": audit_id,
                        "mission_id": mission_id,
                        "component_id": component_id,
                        "event_type": event_type,
                        "reason_code": reason_code,
                        "input_snapshot_json": to_json(input_snapshot) if input_snapshot is not None else None,
                        "candidate_alternatives_json": to_json(candidate_alternatives) if candidate_alternatives is not None else None,
                        "selected_output_json": to_json(selected_output) if selected_output is not None else None,
                        "evidence_refs_json": to_json(evidence_refs) if evidence_refs is not None else None,
                        "versions_json": to_json(versions) if versions is not None else None,
                        "upstream_event_ref": upstream_event_ref,
                        "downstream_event_ref": downstream_event_ref,
                        "trace_id": trace_id,
                    },
                )
        except Exception:
            # Audit persistence failure must be visible to calling components via
            # their own status/exception handling, but it must not recursively fail.
            pass
        return audit_id

    @staticmethod
    def envelope(event_type: str, component_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "event_type": event_type,
            "component_id": component_id,
            "created_at": utcnow_iso(),
            "payload": payload,
        }

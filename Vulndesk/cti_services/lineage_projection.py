from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .common import safe_json_loads, utcnow_iso
from .db_adapter import DbAdapter, make_json_safe


LINEAGE_PROJECTION_SCHEMA_V1 = "cti-lineage-projection-v1"
LINEAGE_PROJECTION_SCOPE_TASK = "TASK"
LINEAGE_PROJECTION_SCOPE_MISSION = "MISSION"


class LineageProjectionError(RuntimeError):
    """Base error for canonical lineage projection failures."""


class LineageProjectionNotFound(LineageProjectionError):
    """Raised when the requested TaskContract does not exist."""


class LineageProjectionSchemaError(LineageProjectionError):
    """Raised when the persisted lineage schema required by the projector is missing."""


class MissionLineageNotFound(LineageProjectionError):
    """Raised when the requested canonical mission root does not exist."""


@dataclass(frozen=True)
class CanonicalLineageEvent:
    sequence_no: int
    event_id: str
    event_schema_version: Optional[str]
    event_type: str
    source_component: Optional[str]
    severity: Optional[str]
    mission_id: Optional[str]
    trace_id: Optional[str]
    proposal_id: Optional[str]
    task_id: Optional[str]
    policy_decision_id: Optional[str]
    authorization_request_id: Optional[str]
    revalidation_id: Optional[str]
    causation_event_id: Optional[str]
    upstream_event_id: Optional[str]
    state_version: Optional[Any]
    plan_version: Optional[Any]
    policy_version: Optional[Any]
    evidence_ref: Optional[str]
    created_at: Optional[Any]
    payload: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return make_json_safe({
            "sequence_no": self.sequence_no,
            "event_id": self.event_id,
            "event_schema_version": self.event_schema_version,
            "event_type": self.event_type,
            "source_component": self.source_component,
            "severity": self.severity,
            "mission_id": self.mission_id,
            "trace_id": self.trace_id,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "policy_decision_id": self.policy_decision_id,
            "authorization_request_id": self.authorization_request_id,
            "revalidation_id": self.revalidation_id,
            "causation_event_id": self.causation_event_id,
            "upstream_event_id": self.upstream_event_id,
            "state_version": self.state_version,
            "plan_version": self.plan_version,
            "policy_version": self.policy_version,
            "evidence_ref": self.evidence_ref,
            "created_at": self.created_at,
            "payload": dict(self.payload or {}),
        })


@dataclass(frozen=True)
class CanonicalCausalEdge:
    cause_event_id: str
    effect_event_id: str
    cause_in_projection: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "edge_type": "CAUSATION",
            "cause_event_id": self.cause_event_id,
            "effect_event_id": self.effect_event_id,
            "cause_in_projection": self.cause_in_projection,
        }


@dataclass(frozen=True)
class CanonicalUpstreamEdge:
    upstream_event_id: str
    local_event_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "edge_type": "UPSTREAM_PROVENANCE",
            "upstream_event_id": self.upstream_event_id,
            "local_event_id": self.local_event_id,
        }


@dataclass
class CanonicalMissionLineageProjection:
    mission_id: str
    mission: Dict[str, Any]
    lifecycle: Dict[str, Any]
    task_lineages: List[Dict[str, Any]]
    events: List[CanonicalLineageEvent]
    causal_edges: List[CanonicalCausalEdge]
    causal_order_event_ids: List[str]
    root_event_ids: List[str]
    decision_traces: List[Dict[str, Any]]
    audit_records: List[Dict[str, Any]]
    structural_facts: Dict[str, Any]
    projection_quality: str
    source_modes: List[str]
    generated_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> Dict[str, Any]:
        return make_json_safe({
            "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
            "projection_scope": LINEAGE_PROJECTION_SCOPE_MISSION,
            "generated_at": self.generated_at,
            "identity": {"mission_id": self.mission_id},
            "mission": self.mission,
            "lifecycle": self.lifecycle,
            "task_lineages": list(self.task_lineages),
            "events": [event.as_dict() for event in self.events],
            "causal_edges": [edge.as_dict() for edge in self.causal_edges],
            "causal_order_event_ids": list(self.causal_order_event_ids),
            "root_event_ids": list(self.root_event_ids),
            "decision_traces": list(self.decision_traces),
            "audit_records": list(self.audit_records),
            "structural_facts": dict(self.structural_facts),
            "projection_metadata": {
                "quality": self.projection_quality,
                "source_modes": list(self.source_modes),
                "task_count": len(self.task_lineages),
                "event_count": len(self.events),
                "causal_edge_count": len(self.causal_edges),
                "root_event_count": len(self.root_event_ids),
                "decision_trace_count": len(self.decision_traces),
                "audit_record_count": len(self.audit_records),
                "governance_correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
                "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
            },
        })


@dataclass
class CanonicalTaskLineageProjection:
    mission_id: str
    task_id: str
    trace_id: Optional[str]
    proposal_id: Optional[str]
    task_contract: Dict[str, Any]
    governance_binding: Dict[str, Any]
    lifecycle: Dict[str, Any]
    events: List[CanonicalLineageEvent]
    causal_edges: List[CanonicalCausalEdge]
    upstream_edges: List[CanonicalUpstreamEdge]
    decision_traces: List[Dict[str, Any]]
    audit_records: List[Dict[str, Any]]
    projection_quality: str
    source_modes: List[str]
    generated_at: str = field(default_factory=utcnow_iso)

    def as_dict(self) -> Dict[str, Any]:
        return make_json_safe({
            "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
            "projection_scope": LINEAGE_PROJECTION_SCOPE_TASK,
            "generated_at": self.generated_at,
            "identity": {
                "mission_id": self.mission_id,
                "task_id": self.task_id,
                "trace_id": self.trace_id,
                "proposal_id": self.proposal_id,
            },
            "task_contract": self.task_contract,
            "governance_binding": self.governance_binding,
            "lifecycle": self.lifecycle,
            "events": [event.as_dict() for event in self.events],
            "causal_edges": [edge.as_dict() for edge in self.causal_edges],
            "upstream_edges": [edge.as_dict() for edge in self.upstream_edges],
            "decision_traces": list(self.decision_traces),
            "audit_records": list(self.audit_records),
            "projection_metadata": {
                "quality": self.projection_quality,
                "source_modes": list(self.source_modes),
                "event_count": len(self.events),
                "causal_edge_count": len(self.causal_edges),
                "upstream_edge_count": len(self.upstream_edges),
                "decision_trace_count": len(self.decision_traces),
                "audit_record_count": len(self.audit_records),
            },
        })


class CanonicalLineageProjector:
    """Stage 2.9.1 deterministic read-side projection over Stage 2.8 lineage data.

    The projector does not create authority, mutate TaskContracts, or repair events.
    It only canonicalizes already-persisted lineage from four local sources:

    * ``cti_task_contracts`` -- authoritative local task/business binding snapshot;
    * ``cti_events`` -- lifecycle and causal event chain;
    * ``cti_decision_traces`` -- decision materialization for the same task lineage;
    * ``cti_audit_log`` -- decision-to-event audit bridge.

    Cross-subsystem Governance identities remain references (``gevent-*``, ``gdec-*``,
    etc.).  Stage 2.9.4 will correlate those references against aptsGSS; this stage
    intentionally does not query or reinterpret the Governance database.
    """

    _REQUIRED_TABLES = (
        "cti_task_contracts",
        "cti_events",
        "cti_decision_traces",
        "cti_audit_log",
    )

    _REQUIRED_COLUMNS: Dict[str, Set[str]] = {
        "cti_task_contracts": {
            "task_id",
            "mission_id",
            "trace_id",
            "policy_decision_id",
            "authorization_request_id",
            "authorization_governance_event_id",
            "pre_dispatch_governance_event_id",
        },
        "cti_events": {
            "event_id",
            "mission_id",
            "trace_id",
            "causation_event_id",
            "upstream_event_id",
            "proposal_id",
            "task_id",
            "policy_decision_id",
            "authorization_request_id",
            "revalidation_id",
        },
        "cti_decision_traces": {
            "trace_id",
            "lineage_trace_id",
            "mission_id",
            "task_id",
            "upstream_event_id",
        },
        "cti_audit_log": {
            "trace_id",
            "mission_id",
            "upstream_event_ref",
            "downstream_event_ref",
        },
    }

    _MISSION_REQUIRED_COLUMNS: Dict[str, Set[str]] = {
        "cti_missions": {
            "mission_id",
            "status",
            "state_version",
            "plan_version",
            "policy_version",
        },
    }

    _MISSION_JSON_COLUMNS = (
        "objective_json",
        "asset_scope_json",
        "intelligence_requirements_json",
        "time_window_json",
        "policy_context_json",
    )

    _EVENT_JSON_COLUMNS = ("payload_json",)
    _DECISION_JSON_COLUMNS = (
        "observations_json",
        "candidate_actions_json",
        "score_breakdown_json",
        "selected_action_json",
        "policy_decision_json",
        "execution_outcome_json",
    )
    _AUDIT_JSON_COLUMNS = (
        "input_snapshot_json",
        "candidate_alternatives_json",
        "selected_output_json",
        "evidence_refs_json",
        "versions_json",
    )
    _TASK_JSON_COLUMNS = (
        "input_refs_json",
        "output_refs_json",
        "constraints_json",
        "retry_policy_json",
        "success_criteria_json",
        "governance_reason_codes_json",
        "governance_constraints_json",
        "governance_request_json",
        "pre_dispatch_reason_codes_json",
    )

    _TERMINAL_CONTRACT_STATES = {
        "COMPLETED",
        "DEGRADED",
        "FAILED",
        "CANCELLED",
        "BLOCKED_REVOKED",
        "BLOCKED",
    }

    _EVENT_STATE_MAP = {
        "TASK_COMMITTED": "COMMITTED",
        "TASK_AUTHORIZATION_REVALIDATED": "AUTHORIZED",
        "TASK_DISPATCHED": "DISPATCHED",
        "TASK_COMPLETED": "COMPLETED",
        "TASK_FAILED": "FAILED",
        "SOURCE_SYNC_COMPLETED": "COMPLETED",
        "SOURCE_SYNC_DEGRADED": "DEGRADED",
        "SOURCE_SYNC_FAILED": "FAILED",
        "TASK_AUTHORIZATION_REVOKED": "REVOKED",
        "TASK_DISPATCH_BLOCKED": "BLOCKED",
        "TASK_REVOCATION_STOP_REQUESTED": "STOP_REQUESTED",
    }

    def __init__(self, db: Optional[DbAdapter] = None):
        self.db = db or DbAdapter()

    def project_task(self, task_id: str) -> Dict[str, Any]:
        key = str(task_id or "").strip()
        if not key:
            raise ValueError("task_id is required")

        self._assert_schema_ready()
        task = self.db.fetch_one(
            "SELECT * FROM cti_task_contracts WHERE task_id=%(task_id)s LIMIT 1",
            {"task_id": key},
        )
        if not task:
            raise LineageProjectionNotFound(f"TaskContract not found: {key}")

        task = self._decode_row(task, self._TASK_JSON_COLUMNS)
        mission_id = self._text(task.get("mission_id"))
        trace_id = self._nullable_text(task.get("trace_id"))
        if not mission_id:
            raise LineageProjectionSchemaError(
                f"TaskContract {key} has no mission_id; canonical projection is not possible"
            )

        event_rows, event_source_modes = self._load_events(
            task_id=key,
            mission_id=mission_id,
            trace_id=trace_id,
        )
        events = [self._canonical_event(i + 1, row) for i, row in enumerate(event_rows)]
        event_ids = {event.event_id for event in events}

        decision_rows, decision_source_modes = self._load_decision_traces(
            task_id=key,
            mission_id=mission_id,
            trace_id=trace_id,
        )
        decision_rows = [self._normalize_decision_trace(row) for row in decision_rows]
        decision_ids = {
            self._text(row.get("trace_id")) for row in decision_rows if row.get("trace_id")
        }

        audit_rows = self._load_audit_records(
            mission_id=mission_id,
            task_id=key,
            event_ids=event_ids,
            decision_trace_ids=decision_ids,
        )
        audit_rows = [self._normalize_audit_record(row) for row in audit_rows]

        causal_edges = self._causal_edges(events)
        upstream_edges = self._upstream_edges(events)
        governance_binding = self._governance_binding(task, events, decision_rows)
        lifecycle = self._derive_lifecycle(task, events)
        proposal_id = self._proposal_id(task, events, decision_rows)

        source_modes = self._dedupe(event_source_modes + decision_source_modes)
        projection_quality = self._projection_quality(events, source_modes)

        projection = CanonicalTaskLineageProjection(
            mission_id=mission_id,
            task_id=key,
            trace_id=trace_id,
            proposal_id=proposal_id,
            task_contract=self._task_contract_snapshot(task),
            governance_binding=governance_binding,
            lifecycle=lifecycle,
            events=events,
            causal_edges=causal_edges,
            upstream_edges=upstream_edges,
            decision_traces=decision_rows,
            audit_records=audit_rows,
            projection_quality=projection_quality,
            source_modes=source_modes,
        )
        return projection.as_dict()

    def project_mission(self, mission_id: str) -> Dict[str, Any]:
        """Reconstruct canonical mission lineage from the persisted Stage 2.8/2.9 read model.

        Stage 2.9.3 composes the Stage 2.9.1 task projection for every TaskContract
        belonging to the mission, then adds mission-wide event ordering and structural
        facts that cannot be resolved inside a single task projection (for example, a
        cross-task causal parent).  This method is read-only: it never repairs rows,
        verifies Governance records, or classifies integrity violations.
        """
        key = str(mission_id or "").strip()
        if not key:
            raise ValueError("mission_id is required")

        self._assert_mission_schema_ready()
        mission = self.db.fetch_one(
            "SELECT * FROM cti_missions WHERE mission_id=%(mission_id)s LIMIT 1",
            {"mission_id": key},
        )
        if not mission:
            raise MissionLineageNotFound(f"Mission not found: {key}")
        mission = self._decode_row(mission, self._MISSION_JSON_COLUMNS)

        task_rows = self.db.fetch_all(
            """
            SELECT task_id
              FROM cti_task_contracts
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": key},
        )
        task_ids = [
            self._text(row.get("task_id"))
            for row in task_rows
            if self._text(row.get("task_id"))
        ]
        task_lineages = [self.project_task(task_id) for task_id in task_ids]

        raw_events = self.db.fetch_all(
            """
            SELECT *
              FROM cti_events
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": key},
        )
        decoded_events = [self._decode_row(row, self._EVENT_JSON_COLUMNS) for row in raw_events]
        decoded_events = self._stable_unique_rows(decoded_events, "event_id")
        events = [self._canonical_event(i + 1, row) for i, row in enumerate(decoded_events)]

        decision_rows = self.db.fetch_all(
            """
            SELECT *
              FROM cti_decision_traces
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": key},
        )
        decision_rows = [
            self._normalize_decision_trace(self._decode_row(row, self._DECISION_JSON_COLUMNS))
            for row in self._stable_unique_rows(decision_rows, "trace_id")
        ]

        audit_rows = self.db.fetch_all(
            """
            SELECT *
              FROM cti_audit_log
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": key},
        )
        audit_rows = [
            self._normalize_audit_record(self._decode_row(row, self._AUDIT_JSON_COLUMNS))
            for row in self._stable_unique_rows(audit_rows, "audit_id")
        ]

        causal_edges = self._causal_edges(events)
        causal_order, order_fully_resolved = self._mission_causal_order(events)
        root_event_ids = [event.event_id for event in events if not event.causation_event_id]
        structural_facts = self._mission_structural_facts(
            task_ids=task_ids,
            task_lineages=task_lineages,
            events=events,
            causal_edges=causal_edges,
            causal_order_fully_resolved=order_fully_resolved,
        )
        lifecycle = self._derive_mission_lifecycle(mission, task_lineages, events)

        task_qualities = [
            str((lineage.get("projection_metadata") or {}).get("quality") or "")
            for lineage in task_lineages
        ]
        source_modes = self._dedupe([
            "MISSION_ROOT",
            "MISSION_EVENT_STREAM" if events else None,
            "MISSION_DECISION_STREAM" if decision_rows else None,
            "MISSION_AUDIT_STREAM" if audit_rows else None,
            *[
                mode
                for lineage in task_lineages
                for mode in ((lineage.get("projection_metadata") or {}).get("source_modes") or [])
            ],
        ])
        if not events:
            quality = "PARTIAL_NO_EVENTS"
        elif any(q == "HISTORICAL_FALLBACK" for q in task_qualities):
            quality = "HISTORICAL_FALLBACK"
        elif task_lineages and all(
            (lineage.get("projection_metadata") or {}).get("event_count", 0) == 0
            for lineage in task_lineages
        ):
            quality = "PARTIAL_NO_TASK_EVENTS"
        else:
            quality = "CANONICAL_V2"

        projection = CanonicalMissionLineageProjection(
            mission_id=key,
            mission=self._mission_snapshot(mission),
            lifecycle=lifecycle,
            task_lineages=task_lineages,
            events=events,
            causal_edges=causal_edges,
            causal_order_event_ids=causal_order,
            root_event_ids=root_event_ids,
            decision_traces=decision_rows,
            audit_records=audit_rows,
            structural_facts=structural_facts,
            projection_quality=quality,
            source_modes=source_modes,
        )
        return projection.as_dict()

    def mission_schema_status(self) -> Dict[str, Any]:
        base = self.schema_status()
        missing_tables = list(base["missing_tables"])
        missing_columns = dict(base["missing_columns"])
        if not self._table_exists("cti_missions"):
            if "cti_missions" not in missing_tables:
                missing_tables.append("cti_missions")
        else:
            columns = self._columns("cti_missions")
            if columns:
                missing = sorted(self._MISSION_REQUIRED_COLUMNS["cti_missions"] - columns)
                if missing:
                    missing_columns["cti_missions"] = missing
        return {
            "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
            "projection_scope": LINEAGE_PROJECTION_SCOPE_MISSION,
            "ready": not missing_tables and not missing_columns,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "source_tables": list(self._REQUIRED_TABLES) + ["cti_missions"],
        }

    def schema_status(self) -> Dict[str, Any]:
        missing_tables: List[str] = []
        missing_columns: Dict[str, List[str]] = {}
        for table in self._REQUIRED_TABLES:
            if not self._table_exists(table):
                missing_tables.append(table)
                continue
            columns = self._columns(table)
            if columns:
                missing = sorted(self._REQUIRED_COLUMNS.get(table, set()) - columns)
                if missing:
                    missing_columns[table] = missing
        return {
            "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
            "ready": not missing_tables and not missing_columns,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "source_tables": list(self._REQUIRED_TABLES),
        }

    # ------------------------------------------------------------------
    # Loading / source selection
    # ------------------------------------------------------------------
    def _assert_schema_ready(self) -> None:
        status = self.schema_status()
        if not status["ready"]:
            raise LineageProjectionSchemaError(
                "Stage 2.9.1 requires the completed Stage 2.8 lineage schema: "
                f"missing_tables={status['missing_tables']}, "
                f"missing_columns={status['missing_columns']}"
            )

    def _assert_mission_schema_ready(self) -> None:
        status = self.mission_schema_status()
        if not status["ready"]:
            raise LineageProjectionSchemaError(
                "Stage 2.9.3 requires the canonical mission/task lineage schema: "
                f"missing_tables={status['missing_tables']}, "
                f"missing_columns={status['missing_columns']}"
            )

    def _load_events(
        self,
        *,
        task_id: str,
        mission_id: str,
        trace_id: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        direct = self.db.fetch_all(
            """
            SELECT *
              FROM cti_events
             WHERE task_id=%(task_id)s
             ORDER BY id ASC
            """,
            {"task_id": task_id},
        )
        rows = [self._decode_row(row, self._EVENT_JSON_COLUMNS) for row in direct]
        modes: List[str] = []
        if rows:
            modes.append("EVENT_TASK_ID")

        # Historical v2 rows may pre-date first-class task_id propagation.  The
        # trace fallback is deliberately restricted to rows without task_id so a
        # different task can never be pulled into this projection merely because
        # a trace value was reused incorrectly.
        if trace_id:
            fallback = self.db.fetch_all(
                """
                SELECT *
                  FROM cti_events
                 WHERE mission_id=%(mission_id)s
                   AND trace_id=%(trace_id)s
                   AND (task_id IS NULL OR task_id='')
                 ORDER BY id ASC
                """,
                {"mission_id": mission_id, "trace_id": trace_id},
            )
            fallback = [self._decode_row(row, self._EVENT_JSON_COLUMNS) for row in fallback]
            if fallback:
                modes.append("EVENT_TRACE_FALLBACK")
                rows.extend(fallback)

        return self._stable_unique_rows(rows, "event_id"), modes

    def _load_decision_traces(
        self,
        *,
        task_id: str,
        mission_id: str,
        trace_id: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        direct = self.db.fetch_all(
            """
            SELECT *
              FROM cti_decision_traces
             WHERE task_id=%(task_id)s
             ORDER BY id ASC
            """,
            {"task_id": task_id},
        )
        rows = [self._decode_row(row, self._DECISION_JSON_COLUMNS) for row in direct]
        modes: List[str] = []
        if rows:
            modes.append("DECISION_TASK_ID")

        if trace_id:
            fallback = self.db.fetch_all(
                """
                SELECT *
                  FROM cti_decision_traces
                 WHERE mission_id=%(mission_id)s
                   AND lineage_trace_id=%(lineage_trace_id)s
                   AND (task_id IS NULL OR task_id='')
                 ORDER BY id ASC
                """,
                {"mission_id": mission_id, "lineage_trace_id": trace_id},
            )
            fallback = [self._decode_row(row, self._DECISION_JSON_COLUMNS) for row in fallback]
            if fallback:
                # ARBITRATION is emitted before the TaskContract exists, so it cannot
                # carry task_id by construction. Correlating it through
                # mission_id + lineage_trace_id is canonical pre-task lineage, not a
                # historical compatibility fallback. Any other task-less decision
                # trace remains conservatively classified as historical fallback.
                pretask = [
                    row
                    for row in fallback
                    if self._text(row.get("decision_type")).upper() == "ARBITRATION"
                ]
                historical = [
                    row
                    for row in fallback
                    if self._text(row.get("decision_type")).upper() != "ARBITRATION"
                ]
                if pretask:
                    modes.append("DECISION_PRETASK_LINEAGE")
                if historical:
                    modes.append("DECISION_LINEAGE_FALLBACK")
                rows.extend(fallback)

        return self._stable_unique_rows(rows, "trace_id"), modes

    def _load_audit_records(
        self,
        *,
        mission_id: str,
        task_id: str,
        event_ids: Set[str],
        decision_trace_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        rows = self.db.fetch_all(
            """
            SELECT *
              FROM cti_audit_log
             WHERE mission_id=%(mission_id)s
             ORDER BY id ASC
            """,
            {"mission_id": mission_id},
        )
        selected: List[Dict[str, Any]] = []
        for raw in rows:
            row = self._decode_row(raw, self._AUDIT_JSON_COLUMNS)
            trace_ref = self._nullable_text(row.get("trace_id"))
            downstream = self._nullable_text(row.get("downstream_event_ref"))
            selected_output = row.get("selected_output_json") or {}
            selected_task_id = None
            if isinstance(selected_output, dict):
                selected_task_id = self._nullable_text(selected_output.get("task_id"))
                selected_action = selected_output.get("selected_action")
                if selected_task_id is None and isinstance(selected_action, dict):
                    selected_task_id = self._nullable_text(selected_action.get("task_id"))
            if (
                (trace_ref and trace_ref in decision_trace_ids)
                or (downstream and downstream in event_ids)
                or selected_task_id == task_id
            ):
                selected.append(row)
        return self._stable_unique_rows(selected, "audit_id")

    # ------------------------------------------------------------------
    # Canonicalization
    # ------------------------------------------------------------------
    def _canonical_event(self, sequence_no: int, row: Dict[str, Any]) -> CanonicalLineageEvent:
        return CanonicalLineageEvent(
            sequence_no=sequence_no,
            event_id=self._text(row.get("event_id")),
            event_schema_version=self._nullable_text(row.get("event_schema_version")),
            event_type=self._text(row.get("event_type") or "UNKNOWN").upper(),
            source_component=self._nullable_text(row.get("source_component")),
            severity=self._nullable_text(row.get("severity")),
            mission_id=self._nullable_text(row.get("mission_id")),
            trace_id=self._nullable_text(row.get("trace_id")),
            proposal_id=self._nullable_text(row.get("proposal_id")),
            task_id=self._nullable_text(row.get("task_id")),
            policy_decision_id=self._nullable_text(row.get("policy_decision_id")),
            authorization_request_id=self._nullable_text(row.get("authorization_request_id")),
            revalidation_id=self._nullable_text(row.get("revalidation_id")),
            causation_event_id=self._nullable_text(row.get("causation_event_id")),
            upstream_event_id=self._nullable_text(row.get("upstream_event_id")),
            state_version=row.get("state_version"),
            plan_version=row.get("plan_version"),
            policy_version=row.get("policy_version"),
            evidence_ref=self._nullable_text(row.get("evidence_ref")),
            created_at=row.get("created_at"),
            payload=dict(row.get("payload_json") or {}),
        )

    def _normalize_decision_trace(self, row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(row)
        normalized.pop("id", None)
        # Give JSON members semantic names while preserving all first-class refs.
        for column in self._DECISION_JSON_COLUMNS:
            if column in normalized:
                normalized[column[:-5] if column.endswith("_json") else column] = normalized.pop(column)
        return make_json_safe(normalized)

    def _normalize_audit_record(self, row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(row)
        normalized.pop("id", None)
        for column in self._AUDIT_JSON_COLUMNS:
            if column in normalized:
                normalized[column[:-5] if column.endswith("_json") else column] = normalized.pop(column)
        return make_json_safe(normalized)

    def _task_contract_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        # Do not invent canonical authority state here.  Preserve the exact local
        # TaskContract snapshot, but convert JSON columns to structured values.
        snapshot = dict(task)
        snapshot.pop("id", None)
        for column in self._TASK_JSON_COLUMNS:
            if column in snapshot:
                snapshot[column[:-5] if column.endswith("_json") else column] = snapshot.pop(column)
        return make_json_safe(snapshot)

    def _governance_binding(
        self,
        task: Dict[str, Any],
        events: Sequence[CanonicalLineageEvent],
        decisions: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        upstream_refs = self._dedupe([
            self._nullable_text(task.get("authorization_governance_event_id")),
            self._nullable_text(task.get("pre_dispatch_governance_event_id")),
            self._nullable_text(task.get("revocation_event_id")),
            *[event.upstream_event_id for event in events],
            *[self._nullable_text(row.get("upstream_event_id")) for row in decisions],
        ])
        required = self._text(task.get("authorization_mode")).upper() == "REQUIRED"
        return make_json_safe({
            "authorization_mode": task.get("authorization_mode"),
            "authority": task.get("authorization_authority"),
            "authority_component": task.get("authorization_authority_component"),
            "policy_decision_id": task.get("policy_decision_id"),
            "authorization_request_id": task.get("authorization_request_id"),
            "approval_request_id": task.get("approval_request_id"),
            "scope_contract_id": task.get("scope_contract_id"),
            "scope_version": task.get("scope_version"),
            "policy_set_id": task.get("policy_set_id"),
            "policy_version": task.get("policy_version"),
            "policy_decision_hash": task.get("policy_decision_hash"),
            "authorization_decision": task.get("authorization_decision"),
            "authorization_status": task.get("authorization_status"),
            "authorization_governance_event_id": task.get("authorization_governance_event_id"),
            "pre_dispatch_revalidation_id": task.get("pre_dispatch_revalidation_id"),
            "pre_dispatch_governance_event_id": task.get("pre_dispatch_governance_event_id"),
            "pre_dispatch_revalidation_status": task.get("pre_dispatch_revalidation_status"),
            "revocation_id": task.get("revocation_id"),
            "revocation_event_id": task.get("revocation_event_id"),
            "revocation_status": task.get("revocation_status"),
            "revocation_decision_status": task.get("revocation_decision_status"),
            "required_authority": required,
            "external_upstream_event_ids": upstream_refs,
            "correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
        })

    def _derive_lifecycle(
        self,
        task: Dict[str, Any],
        events: Sequence[CanonicalLineageEvent],
    ) -> Dict[str, Any]:
        by_type: Dict[str, List[CanonicalLineageEvent]] = {}
        event_state = None
        last_event = None
        for event in events:
            by_type.setdefault(event.event_type, []).append(event)
            last_event = event
            mapped = self._EVENT_STATE_MAP.get(event.event_type)
            if mapped:
                event_state = mapped

        contract_status = self._text(task.get("status") or "UNKNOWN").upper()
        canonical_state = (
            contract_status
            if contract_status in self._TERMINAL_CONTRACT_STATES
            else (event_state or contract_status)
        )
        terminal_event_types = {
            "TASK_COMPLETED",
            "TASK_FAILED",
            "SOURCE_SYNC_COMPLETED",
            "SOURCE_SYNC_DEGRADED",
            "SOURCE_SYNC_FAILED",
            "TASK_DISPATCH_BLOCKED",
            "TASK_REVOCATION_STOP_REQUESTED",
        }
        terminal_events = [event for event in events if event.event_type in terminal_event_types]
        terminal = terminal_events[-1] if terminal_events else None

        return make_json_safe({
            "contract_status": contract_status,
            "event_state": event_state,
            "canonical_state": canonical_state,
            "committed_event_id": self._last_event_id(by_type, "TASK_COMMITTED"),
            "authorization_revalidated_event_id": self._last_event_id(
                by_type, "TASK_AUTHORIZATION_REVALIDATED"
            ),
            "dispatched_event_id": self._last_event_id(by_type, "TASK_DISPATCHED"),
            "terminal_event_id": terminal.event_id if terminal else None,
            "terminal_event_type": terminal.event_type if terminal else None,
            "last_event_id": last_event.event_id if last_event else None,
            "last_event_type": last_event.event_type if last_event else None,
        })

    def _proposal_id(
        self,
        task: Dict[str, Any],
        events: Sequence[CanonicalLineageEvent],
        decisions: Sequence[Dict[str, Any]],
    ) -> Optional[str]:
        for event in events:
            if event.proposal_id:
                return event.proposal_id
        for row in decisions:
            if row.get("proposal_id"):
                return self._nullable_text(row.get("proposal_id"))
        return self._nullable_text(task.get("trace_id"))

    @staticmethod
    def _causal_edges(events: Sequence[CanonicalLineageEvent]) -> List[CanonicalCausalEdge]:
        event_ids = {event.event_id for event in events}
        return [
            CanonicalCausalEdge(
                cause_event_id=str(event.causation_event_id),
                effect_event_id=event.event_id,
                cause_in_projection=str(event.causation_event_id) in event_ids,
            )
            for event in events
            if event.causation_event_id
        ]

    @staticmethod
    def _upstream_edges(events: Sequence[CanonicalLineageEvent]) -> List[CanonicalUpstreamEdge]:
        seen: Set[Tuple[str, str]] = set()
        result: List[CanonicalUpstreamEdge] = []
        for event in events:
            if not event.upstream_event_id:
                continue
            key = (event.upstream_event_id, event.event_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(CanonicalUpstreamEdge(key[0], key[1]))
        return result

    @classmethod
    def _projection_quality(
        cls,
        events: Sequence[CanonicalLineageEvent],
        source_modes: Sequence[str],
    ) -> str:
        if not events:
            return "PARTIAL_NO_EVENTS"
        if any("FALLBACK" in mode for mode in source_modes):
            return "HISTORICAL_FALLBACK"
        return "CANONICAL_V2"

    def _mission_snapshot(self, mission: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = dict(mission)
        snapshot.pop("id", None)
        for column in self._MISSION_JSON_COLUMNS:
            if column in snapshot:
                snapshot[column[:-5] if column.endswith("_json") else column] = snapshot.pop(column)
        return make_json_safe(snapshot)

    def _derive_mission_lifecycle(
        self,
        mission: Dict[str, Any],
        task_lineages: Sequence[Dict[str, Any]],
        events: Sequence[CanonicalLineageEvent],
    ) -> Dict[str, Any]:
        state_counts: Dict[str, int] = {}
        terminal_task_ids: List[str] = []
        nonterminal_task_ids: List[str] = []
        terminal_states = set(self._TERMINAL_CONTRACT_STATES)
        for lineage in task_lineages:
            task_id = self._text((lineage.get("identity") or {}).get("task_id"))
            state = self._text((lineage.get("lifecycle") or {}).get("canonical_state") or "UNKNOWN").upper()
            state_counts[state] = state_counts.get(state, 0) + 1
            if state in terminal_states:
                terminal_task_ids.append(task_id)
            else:
                nonterminal_task_ids.append(task_id)

        last_event = events[-1] if events else None
        status = self._text(mission.get("status") or "UNKNOWN").upper()
        return make_json_safe({
            "mission_status": status,
            "state_version": mission.get("state_version"),
            "plan_version": mission.get("plan_version"),
            "policy_version": mission.get("policy_version"),
            "pip_readiness": mission.get("pip_readiness"),
            "latest_pip_id": mission.get("latest_pip_id"),
            "task_state_counts": state_counts,
            "terminal_task_ids": terminal_task_ids,
            "nonterminal_task_ids": nonterminal_task_ids,
            "all_tasks_terminal": bool(task_lineages) and not nonterminal_task_ids,
            "last_event_id": last_event.event_id if last_event else None,
            "last_event_type": last_event.event_type if last_event else None,
        })

    @classmethod
    def _mission_structural_facts(
        cls,
        *,
        task_ids: Sequence[str],
        task_lineages: Sequence[Dict[str, Any]],
        events: Sequence[CanonicalLineageEvent],
        causal_edges: Sequence[CanonicalCausalEdge],
        causal_order_fully_resolved: bool,
    ) -> Dict[str, Any]:
        task_id_set = set(task_ids)
        orphan_task_event_ids = [
            event.event_id
            for event in events
            if event.task_id and event.task_id not in task_id_set
        ]
        unbound_mission_event_ids = [event.event_id for event in events if not event.task_id]
        unresolved = [
            {
                "effect_event_id": edge.effect_event_id,
                "causation_event_id": edge.cause_event_id,
            }
            for edge in causal_edges
            if not edge.cause_in_projection
        ]
        task_ids_without_events = [
            cls._text((lineage.get("identity") or {}).get("task_id"))
            for lineage in task_lineages
            if int((lineage.get("projection_metadata") or {}).get("event_count") or 0) == 0
        ]
        return make_json_safe({
            "unresolved_causal_references": unresolved,
            "orphan_task_event_ids": orphan_task_event_ids,
            "unbound_mission_event_ids": unbound_mission_event_ids,
            "task_ids_without_events": task_ids_without_events,
            "causal_order_fully_resolved": bool(causal_order_fully_resolved),
            "classification": "STRUCTURAL_FACTS_ONLY_STAGE_2_9_3",
        })

    @classmethod
    def _mission_causal_order(
        cls,
        events: Sequence[CanonicalLineageEvent],
    ) -> Tuple[List[str], bool]:
        """Stable parent-before-child order over known intra-mission causal edges.

        Unknown parents are preserved as unresolved structural facts and do not create
        a synthetic node. If malformed persisted data contains a cycle, remaining nodes
        are appended in persisted order; Stage 2.9.3 reports only that the order is not
        fully resolved and leaves violation classification to Stage 2.9.5.
        """
        if not events:
            return [], True
        position = {event.event_id: idx for idx, event in enumerate(events)}
        by_id = {event.event_id: event for event in events}
        children: Dict[str, List[str]] = {event.event_id: [] for event in events}
        indegree: Dict[str, int] = {event.event_id: 0 for event in events}
        unresolved_parent = False
        for event in events:
            cause = event.causation_event_id
            if not cause:
                continue
            if cause not in by_id:
                unresolved_parent = True
                continue
            children[cause].append(event.event_id)
            indegree[event.event_id] += 1

        ready = sorted(
            [event_id for event_id, degree in indegree.items() if degree == 0],
            key=lambda event_id: position[event_id],
        )
        ordered: List[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for child in sorted(children[current], key=lambda event_id: position[event_id]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort(key=lambda event_id: position[event_id])

        cycle_or_unresolved_internal = len(ordered) != len(events)
        if cycle_or_unresolved_internal:
            seen = set(ordered)
            ordered.extend(event.event_id for event in events if event.event_id not in seen)
        return ordered, not unresolved_parent and not cycle_or_unresolved_internal

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _table_exists(self, table: str) -> bool:
        try:
            return bool(self.db.table_exists(table))
        except Exception:
            return False

    def _columns(self, table: str) -> Set[str]:
        columns_fn = getattr(self.db, "columns", None)
        if not callable(columns_fn):
            return set()
        try:
            return set(columns_fn(table) or set())
        except Exception:
            # Test doubles / compatibility adapters may not expose schema
            # introspection. Unknown columns are not treated as missing here;
            # real DbAdapter exposes them and therefore remains fail-fast.
            return set()

    @classmethod
    def _decode_row(cls, row: Dict[str, Any], json_columns: Iterable[str]) -> Dict[str, Any]:
        decoded = dict(row or {})
        for column in json_columns:
            if column in decoded:
                decoded[column] = safe_json_loads(decoded.get(column), default={})
        return decoded

    @classmethod
    def _stable_unique_rows(cls, rows: Sequence[Dict[str, Any]], identity_key: str) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}
        anonymous: List[Dict[str, Any]] = []
        for row in rows:
            identity = cls._nullable_text(row.get(identity_key))
            if identity:
                unique.setdefault(identity, row)
            else:
                anonymous.append(row)
        ordered = list(unique.values()) + anonymous
        ordered.sort(key=cls._row_sort_key)
        return ordered

    @staticmethod
    def _row_sort_key(row: Dict[str, Any]) -> Tuple[Any, str, str]:
        raw_id = row.get("id")
        try:
            db_id: Any = int(raw_id)
        except Exception:
            db_id = 10**30
        created = str(row.get("created_at") or "")
        identity = str(row.get("event_id") or row.get("trace_id") or row.get("audit_id") or "")
        return db_id, created, identity

    @staticmethod
    def _last_event_id(by_type: Dict[str, List[CanonicalLineageEvent]], event_type: str) -> Optional[str]:
        rows = by_type.get(event_type) or []
        return rows[-1].event_id if rows else None

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _nullable_text(cls, value: Any) -> Optional[str]:
        text = cls._text(value)
        return text or None

    @classmethod
    def _dedupe(cls, values: Iterable[Optional[str]]) -> List[str]:
        seen: Set[str] = set()
        result: List[str] = []
        for value in values:
            text = cls._nullable_text(value)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

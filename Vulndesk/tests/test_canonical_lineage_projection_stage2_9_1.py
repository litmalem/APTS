from __future__ import annotations

from typing import Any, Dict, List

import pytest

from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.lineage_projection import (
    LINEAGE_PROJECTION_SCHEMA_V1,
    CanonicalLineageProjector,
    LineageProjectionNotFound,
    LineageProjectionSchemaError,
)


class ProjectionDb:
    def __init__(
        self,
        *,
        task: Dict[str, Any] | None,
        direct_events: List[Dict[str, Any]] | None = None,
        fallback_events: List[Dict[str, Any]] | None = None,
        direct_decisions: List[Dict[str, Any]] | None = None,
        fallback_decisions: List[Dict[str, Any]] | None = None,
        audits: List[Dict[str, Any]] | None = None,
        missing_table: str | None = None,
        missing_column: tuple[str, str] | None = None,
    ):
        self.task = task
        self.direct_events = direct_events or []
        self.fallback_events = fallback_events or []
        self.direct_decisions = direct_decisions or []
        self.fallback_decisions = fallback_decisions or []
        self.audits = audits or []
        self.missing_table = missing_table
        self.missing_column = missing_column

    def table_exists(self, table: str) -> bool:
        return table != self.missing_table

    def columns(self, table: str):
        required = CanonicalLineageProjector._REQUIRED_COLUMNS.get(table, set())
        cols = set(required) | {"id", "created_at"}
        if self.missing_column and self.missing_column[0] == table:
            cols.discard(self.missing_column[1])
        return cols

    def fetch_one(self, sql: str, params=None):
        if "FROM cti_task_contracts" in sql:
            return dict(self.task) if self.task else None
        raise AssertionError(sql)

    def fetch_all(self, sql: str, params=None):
        if "FROM cti_events" in sql:
            if "task_id=%(task_id)s" in sql and "trace_id=%(trace_id)s" not in sql:
                return [dict(x) for x in self.direct_events]
            return [dict(x) for x in self.fallback_events]
        if "FROM cti_decision_traces" in sql:
            if "task_id=%(task_id)s" in sql and "lineage_trace_id=%(lineage_trace_id)s" not in sql:
                return [dict(x) for x in self.direct_decisions]
            return [dict(x) for x in self.fallback_decisions]
        if "FROM cti_audit_log" in sql:
            return [dict(x) for x in self.audits]
        raise AssertionError(sql)


class NoopAudit:
    def append(self, **kwargs):
        return "audit-test"


class NoopRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class NoopGovernance:
    class _Status:
        def as_dict(self):
            return {}

    status = _Status()


def _task(**overrides):
    row = {
        "id": 11,
        "task_id": "task-291",
        "mission_id": "mission-291",
        "plan_id": "plan-291",
        "assigned_component": "cti_source_sync_connector",
        "task_type": "CTI_SOURCE_SYNC",
        "trace_id": "proposal-291",
        "authorization_mode": "REQUIRED",
        "authorization_authority": "aptsGSS",
        "authorization_authority_component": "GOV-PLANE",
        "authorization_governance_event_id": "gevent-issued-291",
        "policy_decision_id": "gdec-291",
        "authorization_request_id": "greq-291",
        "policy_decision_hash": "a" * 64,
        "authorization_decision": "ALLOW",
        "authorization_status": "ACTIVE",
        "scope_contract_id": "scope-291",
        "scope_version": 4,
        "policy_set_id": "policy-set-291",
        "approval_request_id": None,
        "policy_version": "9",
        "pre_dispatch_revalidation_id": "greval-291",
        "pre_dispatch_governance_event_id": "gevent-reval-291",
        "pre_dispatch_revalidation_status": "VALID",
        "revocation_id": None,
        "revocation_event_id": None,
        "revocation_status": None,
        "revocation_decision_status": None,
        "status": "COMPLETED",
        "input_refs_json": '["in-1"]',
        "output_refs_json": '["out-1"]',
        "constraints_json": '{"scope":"strict"}',
        "retry_policy_json": "{}",
        "success_criteria_json": "{}",
        "governance_reason_codes_json": '["ALLOW_POLICY"]',
        "governance_constraints_json": "{}",
        "governance_request_json": '{"action_class":"READ_ONLY_CTI_ACQUISITION"}',
        "pre_dispatch_reason_codes_json": '["POLICY_DECISION_VALID"]',
        "created_at": "2026-08-20 20:00:00",
    }
    row.update(overrides)
    return row


def _event(
    row_id: int,
    event_id: str,
    event_type: str,
    *,
    cause: str | None = None,
    upstream: str | None = None,
    task_id: str | None = "task-291",
    trace_id: str | None = "proposal-291",
):
    return {
        "id": row_id,
        "event_schema_version": "cti-event-v2",
        "event_id": event_id,
        "mission_id": "mission-291",
        "event_type": event_type,
        "source_component": "CTI-A01",
        "severity": "INFO",
        "trace_id": trace_id,
        "causation_event_id": cause,
        "upstream_event_id": upstream,
        "proposal_id": "proposal-291",
        "task_id": task_id,
        "policy_decision_id": "gdec-291",
        "authorization_request_id": "greq-291",
        "revalidation_id": "greval-291" if "REVALIDATED" in event_type or event_type == "TASK_DISPATCHED" else None,
        "payload_json": '{"task_id":"task-291"}',
        "state_version": 3,
        "plan_version": 2,
        "policy_version": "9",
        "evidence_ref": None,
        "created_at": f"2026-08-20 20:00:0{row_id}",
    }


def _decision(row_id: int, trace_id: str, decision_type: str, downstream: str):
    return {
        "id": row_id,
        "trace_id": trace_id,
        "lineage_trace_id": "proposal-291",
        "mission_id": "mission-291",
        "proposal_id": "proposal-291",
        "task_id": "task-291",
        "policy_decision_id": "gdec-291",
        "authorization_request_id": "greq-291",
        "revalidation_id": "greval-291",
        "upstream_event_id": "gevent-reval-291",
        "component_id": "CTI-A01",
        "decision_type": decision_type,
        "observations_json": '{"source":"test"}',
        "candidate_actions_json": "[]",
        "score_breakdown_json": "{}",
        "selected_action_json": '{"event_id":"%s"}' % downstream,
        "policy_decision_json": '{"decision_id":"gdec-291"}',
        "execution_outcome_json": '{"event_id":"%s"}' % downstream,
        "created_at": f"2026-08-20 20:01:0{row_id}",
    }


def test_projects_governed_task_into_canonical_read_model():
    events = [
        _event(1, "event-commit", "TASK_COMMITTED", upstream="gevent-issued-291"),
        _event(2, "event-revalidated", "TASK_AUTHORIZATION_REVALIDATED", cause="event-commit", upstream="gevent-reval-291"),
        _event(3, "event-dispatch", "TASK_DISPATCHED", cause="event-revalidated"),
        _event(4, "event-complete", "SOURCE_SYNC_COMPLETED", cause="event-dispatch"),
    ]
    decisions = [
        _decision(1, "dtrace-commit", "TASK_COMMIT", "event-commit"),
        _decision(2, "dtrace-reval", "PRE_DISPATCH_REVALIDATION", "event-revalidated"),
        _decision(3, "dtrace-result", "TASK_RESULT", "event-complete"),
    ]
    audits = [
        {
            "id": 1,
            "audit_id": "audit-commit",
            "mission_id": "mission-291",
            "component_id": "CTI-A01",
            "event_type": "orchestration.decision.task_commit",
            "trace_id": "dtrace-commit",
            "downstream_event_ref": "event-commit",
            "upstream_event_ref": "gevent-issued-291",
            "selected_output_json": '{"task_id":"task-291"}',
            "input_snapshot_json": "{}",
            "candidate_alternatives_json": "[]",
            "evidence_refs_json": "[]",
            "versions_json": "{}",
        },
        # Same mission but another task: must not leak into task-291 projection.
        {
            "id": 2,
            "audit_id": "audit-other",
            "mission_id": "mission-291",
            "component_id": "CTI-A01",
            "event_type": "orchestration.decision.task_result",
            "trace_id": "dtrace-other",
            "downstream_event_ref": "event-other",
            "upstream_event_ref": None,
            "selected_output_json": '{"task_id":"task-other"}',
            "input_snapshot_json": "{}",
            "candidate_alternatives_json": "[]",
            "evidence_refs_json": "[]",
            "versions_json": "{}",
        },
    ]

    projector = CanonicalLineageProjector(
        ProjectionDb(task=_task(), direct_events=events, direct_decisions=decisions, audits=audits)
    )
    result = projector.project_task("task-291")

    assert result["projection_schema_version"] == LINEAGE_PROJECTION_SCHEMA_V1
    assert result["projection_scope"] == "TASK"
    assert result["identity"] == {
        "mission_id": "mission-291",
        "task_id": "task-291",
        "trace_id": "proposal-291",
        "proposal_id": "proposal-291",
    }
    assert result["task_contract"]["input_refs"] == ["in-1"]
    assert result["task_contract"]["constraints"] == {"scope": "strict"}
    assert result["governance_binding"]["policy_decision_id"] == "gdec-291"
    assert result["governance_binding"]["correlation_status"] == "NOT_EVALUATED_STAGE_2_9_4"
    assert result["governance_binding"]["external_upstream_event_ids"] == [
        "gevent-issued-291",
        "gevent-reval-291",
    ]
    assert result["lifecycle"]["canonical_state"] == "COMPLETED"
    assert result["lifecycle"]["committed_event_id"] == "event-commit"
    assert result["lifecycle"]["dispatched_event_id"] == "event-dispatch"
    assert result["lifecycle"]["terminal_event_id"] == "event-complete"
    assert [e["event_id"] for e in result["events"]] == [
        "event-commit",
        "event-revalidated",
        "event-dispatch",
        "event-complete",
    ]
    assert result["causal_edges"] == [
        {
            "edge_type": "CAUSATION",
            "cause_event_id": "event-commit",
            "effect_event_id": "event-revalidated",
            "cause_in_projection": True,
        },
        {
            "edge_type": "CAUSATION",
            "cause_event_id": "event-revalidated",
            "effect_event_id": "event-dispatch",
            "cause_in_projection": True,
        },
        {
            "edge_type": "CAUSATION",
            "cause_event_id": "event-dispatch",
            "effect_event_id": "event-complete",
            "cause_in_projection": True,
        },
    ]
    assert [d["decision_type"] for d in result["decision_traces"]] == [
        "TASK_COMMIT",
        "PRE_DISPATCH_REVALIDATION",
        "TASK_RESULT",
    ]
    assert [a["audit_id"] for a in result["audit_records"]] == ["audit-commit"]
    assert result["projection_metadata"]["quality"] == "CANONICAL_V2"
    assert result["projection_metadata"]["source_modes"] == ["EVENT_TASK_ID", "DECISION_TASK_ID"]


def test_internal_task_keeps_governance_null_and_does_not_invent_authority():
    task = _task(
        authorization_mode="NOT_REQUIRED_INTERNAL",
        authorization_authority=None,
        authorization_authority_component=None,
        authorization_governance_event_id=None,
        policy_decision_id=None,
        authorization_request_id=None,
        policy_decision_hash=None,
        authorization_decision=None,
        authorization_status=None,
        pre_dispatch_revalidation_id=None,
        pre_dispatch_governance_event_id=None,
        pre_dispatch_revalidation_status=None,
        status="COMMITTED",
    )
    events = [_event(1, "event-internal-commit", "TASK_COMMITTED", upstream=None)]
    for event in events:
        event["policy_decision_id"] = None
        event["authorization_request_id"] = None
        event["revalidation_id"] = None

    result = CanonicalLineageProjector(
        ProjectionDb(task=task, direct_events=events)
    ).project_task("task-291")

    assert result["governance_binding"]["required_authority"] is False
    assert result["governance_binding"]["policy_decision_id"] is None
    assert result["governance_binding"]["external_upstream_event_ids"] == []
    assert result["lifecycle"]["canonical_state"] == "COMMITTED"


def test_historical_trace_fallback_is_explicit_and_never_relabels_event_task_id():
    fallback = _event(
        1,
        "event-historical",
        "TASK_COMMITTED",
        task_id=None,
        trace_id="proposal-291",
    )
    result = CanonicalLineageProjector(
        ProjectionDb(task=_task(status="COMMITTED"), fallback_events=[fallback])
    ).project_task("task-291")

    assert result["events"][0]["task_id"] is None
    assert result["projection_metadata"]["quality"] == "HISTORICAL_FALLBACK"
    assert "EVENT_TRACE_FALLBACK" in result["projection_metadata"]["source_modes"]


def test_unresolved_cause_is_preserved_but_not_classified_as_violation_yet():
    event = _event(4, "event-complete", "TASK_COMPLETED", cause="event-missing")
    result = CanonicalLineageProjector(
        ProjectionDb(task=_task(), direct_events=[event])
    ).project_task("task-291")

    assert result["causal_edges"] == [
        {
            "edge_type": "CAUSATION",
            "cause_event_id": "event-missing",
            "effect_event_id": "event-complete",
            "cause_in_projection": False,
        }
    ]
    # 2.9.1 preserves structural facts. Integrity/violation classification is 2.9.5.
    assert "integrity" not in result


def test_missing_task_and_missing_schema_fail_closed():
    with pytest.raises(LineageProjectionNotFound):
        CanonicalLineageProjector(ProjectionDb(task=None)).project_task("task-missing")

    with pytest.raises(LineageProjectionSchemaError):
        CanonicalLineageProjector(
            ProjectionDb(task=_task(), missing_column=("cti_events", "causation_event_id"))
        ).project_task("task-291")


def test_orchestrator_exposes_projection_service_without_adding_stage_2_9_2_http_api():
    db = ProjectionDb(task=_task(status="COMMITTED"), direct_events=[_event(1, "event-commit", "TASK_COMMITTED")])
    # Avoid constructing unrelated runtime services; this test is only the 2.9.1
    # orchestrator-to-projector delegation boundary.
    orch = CtiSubsystemOrchestrator.__new__(CtiSubsystemOrchestrator)
    orch.lineage_projector = CanonicalLineageProjector(db)
    result = orch.project_task_lineage("task-291")
    assert result["identity"]["task_id"] == "task-291"
    assert CtiSubsystemOrchestrator.CONTROL_VERSION == "hybrid-event-driven-2.17-health-diagnostics"


def test_pretask_arbitration_lineage_is_canonical_not_historical_fallback():
    arbitration = _decision(1, "arb-291", "ARBITRATION", "event-commit")
    arbitration["task_id"] = None
    arbitration["policy_decision_id"] = None
    arbitration["authorization_request_id"] = None
    arbitration["revalidation_id"] = None
    arbitration["upstream_event_id"] = None

    result = CanonicalLineageProjector(
        ProjectionDb(
            task=_task(
                authorization_mode="NOT_REQUIRED_INTERNAL",
                policy_decision_id=None,
                authorization_request_id=None,
                status="COMPLETED",
            ),
            direct_events=[
                _event(1, "event-commit", "TASK_COMMITTED"),
                _event(2, "event-dispatch", "TASK_DISPATCHED", cause="event-commit"),
                _event(3, "event-complete", "TASK_COMPLETED", cause="event-dispatch"),
            ],
            direct_decisions=[_decision(2, "dtrace-commit", "TASK_COMMIT", "event-commit")],
            fallback_decisions=[arbitration],
        )
    ).project_task("task-291")

    assert result["projection_metadata"]["quality"] == "CANONICAL_V2"
    assert result["projection_metadata"]["source_modes"] == [
        "EVENT_TASK_ID",
        "DECISION_TASK_ID",
        "DECISION_PRETASK_LINEAGE",
    ]
    assert [d["decision_type"] for d in result["decision_traces"]] == [
        "ARBITRATION",
        "TASK_COMMIT",
    ]

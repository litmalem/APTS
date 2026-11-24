from __future__ import annotations

import http.client
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.lineage_projection import (
    LINEAGE_PROJECTION_SCHEMA_V1,
    CanonicalLineageProjector,
    LineageProjectionSchemaError,
    MissionLineageNotFound,
)
from cti_services.pentest_enrichment_api_service import PentestEnrichmentApiService


class MissionProjectionDb:
    def __init__(
        self,
        *,
        mission: Dict[str, Any] | None,
        tasks: List[Dict[str, Any]] | None = None,
        events: List[Dict[str, Any]] | None = None,
        decisions: List[Dict[str, Any]] | None = None,
        audits: List[Dict[str, Any]] | None = None,
        missing_table: str | None = None,
        missing_column: tuple[str, str] | None = None,
    ):
        self.mission = mission
        self.tasks = tasks or []
        self.events = events or []
        self.decisions = decisions or []
        self.audits = audits or []
        self.missing_table = missing_table
        self.missing_column = missing_column

    def table_exists(self, table: str) -> bool:
        return table != self.missing_table

    def columns(self, table: str):
        if table == "cti_missions":
            cols = set(CanonicalLineageProjector._MISSION_REQUIRED_COLUMNS["cti_missions"]) | {
                "id", "created_at"
            }
        else:
            cols = set(CanonicalLineageProjector._REQUIRED_COLUMNS.get(table, set())) | {
                "id", "created_at"
            }
        if self.missing_column and self.missing_column[0] == table:
            cols.discard(self.missing_column[1])
        return cols

    def fetch_one(self, sql: str, params=None):
        params = params or {}
        if "FROM cti_missions" in sql:
            if self.mission and self.mission.get("mission_id") == params.get("mission_id"):
                return dict(self.mission)
            return None
        if "FROM cti_task_contracts" in sql:
            for task in self.tasks:
                if task.get("task_id") == params.get("task_id"):
                    return dict(task)
            return None
        raise AssertionError(sql)

    def fetch_all(self, sql: str, params=None):
        params = params or {}
        if "FROM cti_task_contracts" in sql:
            mission_id = params.get("mission_id")
            return [
                {"task_id": task["task_id"], "id": task.get("id")}
                for task in self.tasks
                if task.get("mission_id") == mission_id
            ]

        if "FROM cti_events" in sql:
            if "task_id=%(task_id)s" in sql and "trace_id=%(trace_id)s" not in sql:
                return [dict(row) for row in self.events if row.get("task_id") == params.get("task_id")]
            if "trace_id=%(trace_id)s" in sql:
                return [
                    dict(row)
                    for row in self.events
                    if row.get("mission_id") == params.get("mission_id")
                    and row.get("trace_id") == params.get("trace_id")
                    and not row.get("task_id")
                ]
            return [dict(row) for row in self.events if row.get("mission_id") == params.get("mission_id")]

        if "FROM cti_decision_traces" in sql:
            if "task_id=%(task_id)s" in sql and "lineage_trace_id=%(lineage_trace_id)s" not in sql:
                return [dict(row) for row in self.decisions if row.get("task_id") == params.get("task_id")]
            if "lineage_trace_id=%(lineage_trace_id)s" in sql:
                return [
                    dict(row)
                    for row in self.decisions
                    if row.get("mission_id") == params.get("mission_id")
                    and row.get("lineage_trace_id") == params.get("lineage_trace_id")
                    and not row.get("task_id")
                ]
            return [dict(row) for row in self.decisions if row.get("mission_id") == params.get("mission_id")]

        if "FROM cti_audit_log" in sql:
            return [dict(row) for row in self.audits if row.get("mission_id") == params.get("mission_id")]
        raise AssertionError(sql)


def _mission(**overrides):
    row = {
        "id": 1,
        "mission_id": "mission-293",
        "objective_json": '{"goal":"lineage"}',
        "asset_scope_json": '["asset-1"]',
        "intelligence_requirements_json": "[]",
        "time_window_json": "{}",
        "policy_context_json": '{"mode":"test"}',
        "status": "COMPLETED",
        "state_version": 8,
        "plan_version": 3,
        "policy_version": "policy-9",
        "pip_readiness": "READY",
        "latest_pip_id": "pip-293",
        "created_at": "2026-08-29 00:00:00",
    }
    row.update(overrides)
    return row


def _task(row_id: int, task_id: str, trace_id: str, **overrides):
    row = {
        "id": row_id,
        "task_id": task_id,
        "mission_id": "mission-293",
        "plan_id": "plan-293",
        "assigned_component": "CTI-A01",
        "task_type": "TEST_TASK",
        "trace_id": trace_id,
        "authorization_mode": "NOT_REQUIRED_INTERNAL",
        "authorization_authority": None,
        "authorization_authority_component": None,
        "authorization_governance_event_id": None,
        "policy_decision_id": None,
        "authorization_request_id": None,
        "pre_dispatch_revalidation_id": None,
        "pre_dispatch_governance_event_id": None,
        "status": "COMPLETED",
        "input_refs_json": "[]",
        "output_refs_json": "[]",
        "constraints_json": "{}",
        "retry_policy_json": "{}",
        "success_criteria_json": "{}",
        "governance_reason_codes_json": "[]",
        "governance_constraints_json": "{}",
        "governance_request_json": "{}",
        "pre_dispatch_reason_codes_json": "[]",
        "created_at": f"2026-08-29 00:00:{row_id:02d}",
    }
    row.update(overrides)
    return row


def _event(row_id: int, event_id: str, event_type: str, *, task_id=None, trace_id=None, cause=None):
    return {
        "id": row_id,
        "event_schema_version": "cti-event-v2",
        "event_id": event_id,
        "mission_id": "mission-293",
        "event_type": event_type,
        "source_component": "CTI-A01",
        "severity": "INFO",
        "trace_id": trace_id,
        "causation_event_id": cause,
        "upstream_event_id": None,
        "proposal_id": trace_id,
        "task_id": task_id,
        "policy_decision_id": None,
        "authorization_request_id": None,
        "revalidation_id": None,
        "payload_json": "{}",
        "state_version": row_id,
        "plan_version": 1,
        "policy_version": "policy-9",
        "evidence_ref": None,
        "created_at": f"2026-08-29 00:01:{row_id:02d}",
    }


def _decision(row_id: int, trace_id: str, task_id: str | None, lineage_trace_id: str):
    return {
        "id": row_id,
        "trace_id": trace_id,
        "lineage_trace_id": lineage_trace_id,
        "mission_id": "mission-293",
        "proposal_id": lineage_trace_id,
        "task_id": task_id,
        "policy_decision_id": None,
        "authorization_request_id": None,
        "revalidation_id": None,
        "upstream_event_id": None,
        "component_id": "CTI-A01",
        "decision_type": "TASK_COMMIT" if task_id else "ARBITRATION",
        "observations_json": "{}",
        "candidate_actions_json": "[]",
        "score_breakdown_json": "{}",
        "selected_action_json": "{}",
        "policy_decision_json": "{}",
        "execution_outcome_json": "{}",
        "created_at": f"2026-08-29 00:02:{row_id:02d}",
    }


def _audit(row_id: int, audit_id: str, task_id: str):
    return {
        "id": row_id,
        "audit_id": audit_id,
        "mission_id": "mission-293",
        "component_id": "CTI-A01",
        "event_type": "orchestration.decision.task_commit",
        "trace_id": f"decision-{task_id}",
        "upstream_event_ref": None,
        "downstream_event_ref": f"{task_id}-commit",
        "input_snapshot_json": "{}",
        "candidate_alternatives_json": "[]",
        "selected_output_json": json.dumps({"task_id": task_id}),
        "evidence_refs_json": "[]",
        "versions_json": "{}",
        "created_at": f"2026-08-29 00:03:{row_id:02d}",
    }


def test_reconstructs_whole_mission_and_resolves_cross_task_causation():
    tasks = [_task(1, "task-a", "proposal-a"), _task(2, "task-b", "proposal-b")]
    events = [
        _event(1, "mission-start", "MISSION_STARTED"),
        _event(2, "task-a-commit", "TASK_COMMITTED", task_id="task-a", trace_id="proposal-a", cause="mission-start"),
        _event(3, "task-a-dispatch", "TASK_DISPATCHED", task_id="task-a", trace_id="proposal-a", cause="task-a-commit"),
        _event(4, "task-a-complete", "TASK_COMPLETED", task_id="task-a", trace_id="proposal-a", cause="task-a-dispatch"),
        _event(5, "task-b-commit", "TASK_COMMITTED", task_id="task-b", trace_id="proposal-b", cause="task-a-complete"),
        _event(6, "task-b-dispatch", "TASK_DISPATCHED", task_id="task-b", trace_id="proposal-b", cause="task-b-commit"),
        _event(7, "task-b-complete", "TASK_COMPLETED", task_id="task-b", trace_id="proposal-b", cause="task-b-dispatch"),
        _event(8, "pip-ready", "PIP_READY", cause="task-b-complete"),
    ]
    decisions = [
        _decision(1, "arb-a", None, "proposal-a"),
        _decision(2, "decision-task-a", "task-a", "proposal-a"),
        _decision(3, "decision-task-b", "task-b", "proposal-b"),
    ]
    audits = [_audit(1, "audit-a", "task-a"), _audit(2, "audit-b", "task-b")]

    result = CanonicalLineageProjector(
        MissionProjectionDb(mission=_mission(), tasks=tasks, events=events, decisions=decisions, audits=audits)
    ).project_mission("mission-293")

    assert result["projection_schema_version"] == LINEAGE_PROJECTION_SCHEMA_V1
    assert result["projection_scope"] == "MISSION"
    assert result["identity"] == {"mission_id": "mission-293"}
    assert result["mission"]["objective"] == {"goal": "lineage"}
    assert [x["identity"]["task_id"] for x in result["task_lineages"]] == ["task-a", "task-b"]
    assert all(x["projection_scope"] == "TASK" for x in result["task_lineages"])

    # Each task projection intentionally cannot resolve a parent owned by another
    # mission/task scope; Stage 2.9.3 resolves it at mission scope.
    task_b = result["task_lineages"][1]
    assert task_b["causal_edges"][0]["cause_event_id"] == "task-a-complete"
    assert task_b["causal_edges"][0]["cause_in_projection"] is False
    mission_edge = next(e for e in result["causal_edges"] if e["effect_event_id"] == "task-b-commit")
    assert mission_edge["cause_in_projection"] is True

    assert result["causal_order_event_ids"] == [e["event_id"] for e in result["events"]]
    assert result["root_event_ids"] == ["mission-start"]
    assert result["lifecycle"]["mission_status"] == "COMPLETED"
    assert result["lifecycle"]["task_state_counts"] == {"COMPLETED": 2}
    assert result["lifecycle"]["all_tasks_terminal"] is True
    assert result["lifecycle"]["last_event_id"] == "pip-ready"
    assert result["structural_facts"]["unresolved_causal_references"] == []
    assert result["structural_facts"]["orphan_task_event_ids"] == []
    assert result["structural_facts"]["causal_order_fully_resolved"] is True
    assert result["projection_metadata"]["governance_correlation_status"] == "NOT_EVALUATED_STAGE_2_9_4"
    assert result["projection_metadata"]["integrity_classification_status"] == "NOT_EVALUATED_STAGE_2_9_5"
    assert "integrity" not in result


def test_preserves_orphan_and_missing_parent_as_structural_facts_without_violation_classification():
    tasks = [_task(1, "task-c", "proposal-c", status="COMMITTED")]
    events = [
        _event(1, "mission-start", "MISSION_STARTED"),
        _event(2, "ghost-event", "TASK_COMPLETED", task_id="task-ghost", trace_id="proposal-ghost", cause="missing-parent"),
    ]

    result = CanonicalLineageProjector(
        MissionProjectionDb(mission=_mission(status="RUNNING"), tasks=tasks, events=events)
    ).project_mission("mission-293")

    facts = result["structural_facts"]
    assert facts["orphan_task_event_ids"] == ["ghost-event"]
    assert facts["task_ids_without_events"] == ["task-c"]
    assert facts["unresolved_causal_references"] == [
        {"effect_event_id": "ghost-event", "causation_event_id": "missing-parent"}
    ]
    assert facts["causal_order_fully_resolved"] is False
    assert facts["classification"] == "STRUCTURAL_FACTS_ONLY_STAGE_2_9_3"
    assert "violations" not in result
    assert "integrity" not in result


def test_mission_reconstruction_fails_closed_for_missing_root_or_schema():
    with pytest.raises(MissionLineageNotFound):
        CanonicalLineageProjector(MissionProjectionDb(mission=None)).project_mission("mission-missing")

    with pytest.raises(LineageProjectionSchemaError):
        CanonicalLineageProjector(
            MissionProjectionDb(mission=_mission(), missing_table="cti_missions")
        ).project_mission("mission-293")

    with pytest.raises(LineageProjectionSchemaError):
        CanonicalLineageProjector(
            MissionProjectionDb(mission=_mission(), missing_column=("cti_events", "causation_event_id"))
        ).project_mission("mission-293")


def test_orchestrator_exposes_mission_projection_service_boundary():
    orch = CtiSubsystemOrchestrator.__new__(CtiSubsystemOrchestrator)
    orch.lineage_projector = SimpleNamespace(project_mission=lambda mission_id: {"mission_id": mission_id})
    assert orch.project_mission_lineage("mission-293") == {"mission_id": "mission-293"}
    assert CtiSubsystemOrchestrator.CONTROL_VERSION == "hybrid-event-driven-2.17-health-diagnostics"


class ProbeRegistry:
    def update_status(self, *args, **kwargs):
        return None

    def list_services(self):
        return []


class MissionProbeOrchestrator:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.requested = []
        self.dispatcher = SimpleNamespace(is_running=False)
        self.event_bus = SimpleNamespace(pending_count=lambda: 0)
        self.governance = SimpleNamespace(status=SimpleNamespace(as_dict=lambda: {}))

    def start_dispatcher(self):
        self.dispatcher.is_running = True

    def stop_dispatcher(self):
        self.dispatcher.is_running = False

    def project_mission_lineage(self, mission_id: str):
        self.requested.append(mission_id)
        if self.error:
            raise self.error
        return self.result

    def get_mission_status(self, mission_id: str):
        return {"mission_id": mission_id, "status": "COMPLETED"}


@pytest.fixture
def mission_probe_server():
    servers = []

    def _start(*, result=None, error=None):
        api = PentestEnrichmentApiService.__new__(PentestEnrichmentApiService)
        api.host = "127.0.0.1"
        api.port = 0
        api.registry = ProbeRegistry()
        api.orchestrator = MissionProbeOrchestrator(result=result, error=error)
        api.facade = object()
        api._server = None
        api._thread = None
        api.start()
        servers.append(api)
        return api

    yield _start
    for api in servers:
        api.stop()


def _get(api: PentestEnrichmentApiService, path: str):
    port = api._server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        headers = {k: v for k, v in response.getheaders()}
        return response.status, body, headers
    finally:
        conn.close()


def _mission_projection():
    return {
        "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
        "projection_scope": "MISSION",
        "identity": {"mission_id": "mission-293"},
        "task_lineages": [],
        "events": [],
        "causal_edges": [],
        "causal_order_event_ids": [],
        "root_event_ids": [],
        "structural_facts": {},
        "projection_metadata": {
            "governance_correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        },
    }


def test_mission_lineage_http_probe_success_and_route_precedence(mission_probe_server):
    api = mission_probe_server(result=_mission_projection())

    status, payload, headers = _get(api, "/api/cti/missions/mission-293/lineage")
    assert status == 200
    assert payload["status"] == "completed"
    assert payload["mission_id"] == "mission-293"
    assert payload["lineage"]["projection_scope"] == "MISSION"
    assert api.orchestrator.requested == ["mission-293"]
    assert headers["X-CTI-Control"] == "hybrid-event-driven-2.17-health-diagnostics"

    # Existing mission-status endpoint remains unchanged and must not be captured
    # by the new /lineage route.
    status, payload, _ = _get(api, "/api/cti/missions/mission-293")
    assert status == 200
    assert payload["mission"]["status"] == "COMPLETED"
    assert api.orchestrator.requested == ["mission-293"]


def test_mission_lineage_http_probe_error_contract(mission_probe_server):
    api = mission_probe_server(error=MissionLineageNotFound("Mission not found: missing"))
    status, payload, _ = _get(api, "/api/cti/missions/missing/lineage")
    assert status == 404
    assert payload["error_code"] == "MISSION_LINEAGE_NOT_FOUND"
    assert "traceback" not in payload

    api2 = mission_probe_server(error=LineageProjectionSchemaError("schema missing"))
    status, payload, _ = _get(api2, "/api/cti/missions/mission-293/lineage")
    assert status == 503
    assert payload["error_code"] == "LINEAGE_SCHEMA_UNAVAILABLE"
    assert "traceback" not in payload

    api3 = mission_probe_server(result=_mission_projection())
    status, payload, _ = _get(api3, "/api/cti/missions/%20/lineage")
    assert status == 400
    assert payload["error_code"] == "INVALID_MISSION_ID"
    assert api3.orchestrator.requested == []


def test_stage_2_9_3_interface_catalog_advertises_mission_lineage_probe():
    from cti_services.interface_catalog import provided_interfaces

    interfaces = provided_interfaces(host="127.0.0.1", port=8765)
    assert any("GET /api/cti/missions/{mission_id}/lineage" in row.interface for row in interfaces)

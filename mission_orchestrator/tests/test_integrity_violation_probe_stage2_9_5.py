from __future__ import annotations

import http.client
import json
from types import SimpleNamespace

import pytest

from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.integrity_probe import INTEGRITY_PROBE_SCHEMA_V1, IntegrityViolationProbe
from cti_services.lineage_projection import LineageProjectionNotFound, MissionLineageNotFound
from cti_services.pentest_enrichment_api_service import PentestEnrichmentApiService


def _event(seq, event_type, *, decision_id="gdec-295", upstream=None):
    payload = {"task_id": "task-295"}
    if decision_id:
        payload["policy_decision_id"] = decision_id
    return {
        "sequence_no": seq,
        "event_id": f"event-{seq}",
        "event_type": event_type,
        "task_id": "task-295",
        "policy_decision_id": decision_id,
        "upstream_event_id": upstream,
        "payload": payload,
    }


def _task(*, status="COMPLETED", events=None, policy_decision_id="gdec-295", scope="scope-295", correlation=None):
    if events is None:
        events = [
            _event(1, "TASK_COMMITTED", decision_id=policy_decision_id),
            _event(2, "TASK_AUTHORIZATION_REVALIDATED", decision_id=policy_decision_id),
            _event(3, "TASK_DISPATCHED", decision_id=policy_decision_id),
            _event(4, "TASK_COMPLETED", decision_id=policy_decision_id),
        ]
    if correlation is None:
        correlation = {
            "task_id": "task-295",
            "status": "CORRELATED",
            "required_authority": True,
            "references": [
                {"kind": "POLICY_DECISION", "reference_id": "gdec-295", "status": "MATCH", "optional": False},
                {"kind": "AUTHORIZATION_REQUEST", "reference_id": "greq-295", "status": "MATCH", "optional": False},
                {"kind": "SCOPE_CONTRACT", "reference_id": "scope-295", "status": "MATCH", "optional": False},
                {"kind": "AUTHORIZATION_GOVERNANCE_EVENT", "reference_id": "gevent-295", "status": "MATCH", "optional": False},
            ],
            "field_comparisons": [
                {"field": "decision.scope_contract_id", "local": scope, "authoritative": scope, "status": "MATCH"},
                {"field": "decision.decision_hash", "local": "a" * 64, "authoritative": "a" * 64, "status": "MATCH"},
            ],
            "coverage_complete": True,
            "missing_required_reference_count": 0,
            "mismatch_count": 0,
        }
    return {
        "projection_schema_version": "cti-lineage-projection-v1",
        "projection_scope": "TASK",
        "identity": {"mission_id": "mission-295", "task_id": "task-295", "trace_id": "trace-295"},
        "task_contract": {"task_id": "task-295", "mission_id": "mission-295", "status": status, "policy_decision_id": policy_decision_id, "scope_contract_id": scope},
        "governance_binding": {
            "authorization_mode": "REQUIRED",
            "required_authority": True,
            "policy_decision_id": policy_decision_id,
            "authorization_request_id": "greq-295",
            "scope_contract_id": scope,
            "correlation_status": correlation.get("status"),
        },
        "lifecycle": {"contract_status": status, "canonical_state": status},
        "events": events,
        "causal_edges": [],
        "upstream_edges": [],
        "decision_traces": [],
        "audit_records": [],
        "governance_correlation": {
            "schema_version": "cti-governance-correlation-v1",
            "scope": "TASK",
            "mission_id": "mission-295",
            "task_id": "task-295",
            "status": correlation.get("status"),
            "task_correlation": correlation,
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        },
        "projection_metadata": {"quality": "CANONICAL_V2", "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5"},
    }


def _codes(result):
    return {row["code"] for row in result["integrity_probe"]["violations"]}


def test_clean_governed_task_passes_stage_2_9_5_integrity_probe():
    result = IntegrityViolationProbe().probe_task(_task())
    probe = result["integrity_probe"]
    assert probe["schema_version"] == INTEGRITY_PROBE_SCHEMA_V1
    assert probe["status"] == "PASS"
    assert probe["violation_count"] == 0
    assert probe["verification_complete"] is True
    assert result["projection_metadata"]["integrity_classification_status"] == "PASS"
    assert result["governance_correlation"]["integrity_classification_status"] == "PASS"


def test_dispatched_without_policydecision_is_critical_violation():
    events = [
        _event(1, "TASK_COMMITTED", decision_id=None),
        _event(2, "TASK_DISPATCHED", decision_id=None),
    ]
    correlation = {
        "task_id": "task-295",
        "status": "PARTIAL",
        "required_authority": True,
        "references": [
            {"kind": "POLICY_DECISION", "reference_id": None, "status": "MISSING_LOCAL_REFERENCE", "optional": False},
        ],
        "field_comparisons": [],
    }
    result = IntegrityViolationProbe().probe_task(_task(status="RUNNING", events=events, policy_decision_id=None, correlation=correlation))
    assert result["integrity_probe"]["status"] == "VIOLATION_DETECTED"
    assert "DISPATCH_WITHOUT_POLICY_DECISION" in _codes(result)
    assert result["integrity_probe"]["severity_counts"]["CRITICAL"] >= 1


def test_dispatch_after_revocation_is_critical_violation():
    events = [
        _event(1, "TASK_COMMITTED"),
        _event(2, "TASK_AUTHORIZATION_REVOKED", upstream="gevent-revoke"),
        _event(3, "TASK_DISPATCHED"),
    ]
    result = IntegrityViolationProbe().probe_task(_task(status="RUNNING", events=events))
    assert "DISPATCH_AFTER_REVOCATION" in _codes(result)
    violation = next(v for v in result["integrity_probe"]["violations"] if v["code"] == "DISPATCH_AFTER_REVOCATION")
    assert violation["severity"] == "CRITICAL"


def test_correct_blocking_after_revocation_is_not_a_violation():
    events = [
        _event(1, "TASK_COMMITTED"),
        _event(2, "TASK_AUTHORIZATION_REVOKED", upstream="gevent-revoke"),
        _event(3, "TASK_DISPATCH_BLOCKED", upstream="gevent-revoke"),
    ]
    result = IntegrityViolationProbe().probe_task(_task(status="BLOCKED_REVOKED", events=events))
    assert result["integrity_probe"]["status"] == "PASS"
    assert "DISPATCH_AFTER_REVOCATION" not in _codes(result)
    revocation_check = next(c for c in result["integrity_probe"]["checks"] if c["invariant"] == "REVOCATION_PREVENTS_LATER_DISPATCH")
    assert revocation_check["status"] == "PASS"
    assert revocation_check["evidence"]["classification"] == "CORRECTLY_BLOCKED_AFTER_REVOCATION"


def test_task_scope_policy_scope_mismatch_is_explicit_violation():
    correlation = {
        "task_id": "task-295",
        "status": "PARTIAL",
        "required_authority": True,
        "references": [
            {"kind": "POLICY_DECISION", "reference_id": "gdec-295", "status": "MATCH", "optional": False},
        ],
        "field_comparisons": [
            {"field": "decision.scope_contract_id", "local": "scope-local", "authoritative": "scope-authoritative", "status": "MISMATCH"},
        ],
    }
    result = IntegrityViolationProbe().probe_task(_task(scope="scope-local", correlation=correlation))
    assert "TASK_SCOPE_POLICY_SCOPE_MISMATCH" in _codes(result)
    # The specific invariant owns this mismatch; do not double-count it as generic.
    assert [v["code"] for v in result["integrity_probe"]["violations"]].count("GOVERNANCE_FIELD_MISMATCH") == 0


def test_completed_without_dispatched_is_lineage_violation():
    events = [
        _event(1, "TASK_COMMITTED"),
        _event(2, "TASK_COMPLETED"),
    ]
    result = IntegrityViolationProbe().probe_task(_task(status="COMPLETED", events=events))
    assert "COMPLETED_WITHOUT_DISPATCHED" in _codes(result)


def test_missing_authoritative_reference_becomes_stage_2_9_5_violation():
    correlation = {
        "task_id": "task-295",
        "status": "PARTIAL",
        "required_authority": True,
        "references": [
            {"kind": "POLICY_DECISION", "reference_id": "gdec-missing", "status": "MISSING_GOVERNANCE_RECORD", "optional": False},
        ],
        "field_comparisons": [
            {"field": "decision.scope_contract_id", "local": "scope-295", "authoritative": "scope-295", "status": "MATCH"},
        ],
    }
    result = IntegrityViolationProbe().probe_task(_task(correlation=correlation))
    assert "GOVERNANCE_REQUIRED_REFERENCE_MISSING" in _codes(result)


def test_governance_outage_is_unverifiable_not_invented_violation_when_local_lineage_is_clean():
    task = _task()
    task["governance_correlation"] = {
        "scope": "TASK",
        "mission_id": "mission-295",
        "task_id": "task-295",
        "status": "UNAVAILABLE",
        "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
    }
    result = IntegrityViolationProbe().probe_task(task)
    assert result["integrity_probe"]["status"] == "UNVERIFIABLE"
    assert result["integrity_probe"]["violation_count"] == 0
    assert "GOVERNANCE_CORRELATION_UNAVAILABLE" in result["integrity_probe"]["verification_reasons"]


def _mission(task_lineage, *, external_missing=False, correlation_status="CORRELATED"):
    task_corr = (task_lineage.get("governance_correlation") or {}).get("task_correlation")
    return {
        "projection_schema_version": "cti-lineage-projection-v1",
        "projection_scope": "MISSION",
        "identity": {"mission_id": "mission-295"},
        "mission": {"mission_id": "mission-295", "status": "COMPLETED"},
        "lifecycle": {"mission_status": "COMPLETED"},
        "task_lineages": [task_lineage],
        "events": list(task_lineage.get("events") or []),
        "causal_edges": [],
        "causal_order_event_ids": [],
        "root_event_ids": [],
        "decision_traces": [],
        "audit_records": [],
        "structural_facts": {},
        "governance_correlation": {
            "schema_version": "cti-governance-correlation-v1",
            "scope": "MISSION",
            "mission_id": "mission-295",
            "status": correlation_status,
            "task_correlations": [task_corr] if task_corr else [],
            "external_event_correlations": ([{
                "governance_event_id": "gevent-missing",
                "local_event_id": "event-ext",
                "local_event_type": "POLICY_CHANGED",
                "status": "MISSING_GOVERNANCE_RECORD",
            }] if external_missing else []),
            "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5",
        },
        "projection_metadata": {"quality": "CANONICAL_V2", "integrity_classification_status": "NOT_EVALUATED_STAGE_2_9_5"},
    }


def test_mission_probe_aggregates_task_and_external_event_violations():
    bad_task = _task(events=[_event(1, "TASK_COMMITTED"), _event(2, "TASK_COMPLETED")])
    result = IntegrityViolationProbe().probe_mission(_mission(bad_task, external_missing=True))
    probe = result["integrity_probe"]
    assert probe["status"] == "VIOLATION_DETECTED"
    codes = {row["code"] for row in probe["violations"]}
    assert "COMPLETED_WITHOUT_DISPATCHED" in codes
    assert "GOVERNANCE_EVENT_REFERENCE_MISSING" in codes
    assert probe["summary"]["violated_task_count"] == 1
    assert result["projection_metadata"]["integrity_violation_count"] == probe["violation_count"]


class ProbeRegistry:
    def update_status(self, *args, **kwargs):
        return None

    def list_services(self):
        return []


class ApiOrchestrator:
    def __init__(self, task_result=None, mission_result=None, error=None):
        self.task_result = task_result
        self.mission_result = mission_result
        self.error = error
        self.task_requests = []
        self.mission_requests = []
        self.dispatcher = SimpleNamespace(is_running=False)
        self.event_bus = SimpleNamespace(pending_count=lambda: 0)
        self.governance = SimpleNamespace(status=SimpleNamespace(as_dict=lambda: {}))

    def start_dispatcher(self):
        self.dispatcher.is_running = True

    def stop_dispatcher(self):
        self.dispatcher.is_running = False

    def probe_task_integrity(self, task_id):
        self.task_requests.append(task_id)
        if self.error:
            raise self.error
        return self.task_result

    def probe_mission_integrity(self, mission_id):
        self.mission_requests.append(mission_id)
        if self.error:
            raise self.error
        return self.mission_result

    def get_mission_status(self, mission_id):
        return {"mission_id": mission_id, "status": "COMPLETED"}


@pytest.fixture
def integrity_server():
    servers = []

    def _start(*, task_result=None, mission_result=None, error=None):
        api = PentestEnrichmentApiService.__new__(PentestEnrichmentApiService)
        api.host = "127.0.0.1"
        api.port = 0
        api.registry = ProbeRegistry()
        api.orchestrator = ApiOrchestrator(task_result=task_result, mission_result=mission_result, error=error)
        api.facade = object()
        api._server = None
        api._thread = None
        api.start()
        servers.append(api)
        return api

    yield _start
    for api in servers:
        api.stop()


def _get(api, path):
    port = api._server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        headers = dict(response.getheaders())
        return response.status, payload, headers
    finally:
        conn.close()


def test_task_and_mission_integrity_http_probes_have_route_precedence_and_current_control(integrity_server):
    task_result = {"schema_version": INTEGRITY_PROBE_SCHEMA_V1, "scope": "TASK", "status": "PASS"}
    mission_result = {"schema_version": INTEGRITY_PROBE_SCHEMA_V1, "scope": "MISSION", "status": "PASS"}
    api = integrity_server(task_result=task_result, mission_result=mission_result)

    status, payload, headers = _get(api, "/api/cti/tasks/task-295/integrity")
    assert status == 200
    assert payload["integrity"] == task_result
    assert api.orchestrator.task_requests == ["task-295"]
    assert headers["X-CTI-Control"] == "hybrid-event-driven-2.17-health-diagnostics"

    status, payload, _ = _get(api, "/api/cti/missions/mission-295/integrity")
    assert status == 200
    assert payload["integrity"] == mission_result
    assert api.orchestrator.mission_requests == ["mission-295"]

    status, payload, _ = _get(api, "/api/cti/missions/mission-295")
    assert status == 200
    assert payload["mission"]["status"] == "COMPLETED"


def test_integrity_http_probe_returns_clean_404_contract(integrity_server):
    api = integrity_server(error=LineageProjectionNotFound("TaskContract not found: missing"))
    status, payload, _ = _get(api, "/api/cti/tasks/missing/integrity")
    assert status == 404
    assert payload["error_code"] == "TASK_LINEAGE_NOT_FOUND"
    assert "traceback" not in payload

    api.stop()
    api = integrity_server(error=MissionLineageNotFound("Mission not found: missing"))
    status, payload, _ = _get(api, "/api/cti/missions/missing/integrity")
    assert status == 404
    assert payload["error_code"] == "MISSION_LINEAGE_NOT_FOUND"
    assert "traceback" not in payload


def test_stage_2_9_5_control_version_and_interface_catalog_are_current():
    from cti_services.interface_catalog import provided_interfaces

    assert CtiSubsystemOrchestrator.CONTROL_VERSION == "hybrid-event-driven-2.17-health-diagnostics"
    interfaces = provided_interfaces(host="127.0.0.1", port=8765)
    assert any("GET /api/cti/tasks/{task_id}/integrity" in row.interface for row in interfaces)
    assert any("GET /api/cti/missions/{mission_id}/integrity" in row.interface for row in interfaces)

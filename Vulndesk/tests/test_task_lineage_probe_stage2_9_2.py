from __future__ import annotations

import http.client
import json
from types import SimpleNamespace

import pytest

from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator
from cti_services.lineage_projection import (
    LINEAGE_PROJECTION_SCHEMA_V1,
    LineageProjectionNotFound,
    LineageProjectionSchemaError,
)
from cti_services.pentest_enrichment_api_service import PentestEnrichmentApiService


class ProbeRegistry:
    def __init__(self):
        self.status_updates = []

    def update_status(self, *args, **kwargs):
        self.status_updates.append((args, kwargs))

    def list_services(self):
        return []


class ProbeOrchestrator:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.requested_task_ids = []
        self.started = False
        self.dispatcher = SimpleNamespace(is_running=False)
        self.event_bus = SimpleNamespace(pending_count=lambda: 0)
        self.governance = SimpleNamespace(status=SimpleNamespace(as_dict=lambda: {}))

    def start_dispatcher(self):
        self.started = True
        self.dispatcher.is_running = True

    def stop_dispatcher(self):
        self.started = False
        self.dispatcher.is_running = False

    def project_task_lineage(self, task_id: str):
        self.requested_task_ids.append(task_id)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def probe_server():
    servers = []

    def _start(*, result=None, error=None):
        api = PentestEnrichmentApiService.__new__(PentestEnrichmentApiService)
        api.host = "127.0.0.1"
        api.port = 0
        api.registry = ProbeRegistry()
        api.orchestrator = ProbeOrchestrator(result=result, error=error)
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
        payload = json.loads(response.read().decode("utf-8"))
        headers = {k: v for k, v in response.getheaders()}
        return response.status, payload, headers
    finally:
        conn.close()


def _projection(task_id="task-292"):
    return {
        "projection_schema_version": LINEAGE_PROJECTION_SCHEMA_V1,
        "projection_scope": "TASK",
        "identity": {
            "mission_id": "mission-292",
            "task_id": task_id,
            "trace_id": "proposal-292",
            "proposal_id": "proposal-292",
        },
        "task_contract": {"task_id": task_id, "status": "COMPLETED"},
        "governance_binding": {
            "policy_decision_id": "gdec-292",
            "correlation_status": "NOT_EVALUATED_STAGE_2_9_4",
        },
        "lifecycle": {"canonical_state": "COMPLETED"},
        "events": [],
        "causal_edges": [],
        "upstream_edges": [],
        "decision_traces": [],
        "audit_records": [],
        "projection_metadata": {"quality": "CANONICAL_V2"},
    }


def test_task_lineage_probe_delegates_to_canonical_projection_and_returns_envelope(probe_server):
    projection = _projection()
    api = probe_server(result=projection)

    status, payload, headers = _get(api, "/api/cti/tasks/task-292/lineage")

    assert status == 200
    assert payload == {
        "status": "completed",
        "task_id": "task-292",
        "lineage": projection,
    }
    assert api.orchestrator.requested_task_ids == ["task-292"]
    assert headers["X-CTI-Control"] == "hybrid-event-driven-2.17-health-diagnostics"


def test_task_lineage_probe_decodes_task_id_once_before_projection(probe_server):
    projection = _projection("task 292")
    api = probe_server(result=projection)

    status, payload, _ = _get(api, "/api/cti/tasks/task%20292/lineage")

    assert status == 200
    assert payload["task_id"] == "task 292"
    assert api.orchestrator.requested_task_ids == ["task 292"]


def test_task_lineage_probe_returns_404_for_unknown_task_without_generic_traceback(probe_server):
    api = probe_server(error=LineageProjectionNotFound("TaskContract not found: task-missing"))

    status, payload, _ = _get(api, "/api/cti/tasks/task-missing/lineage")

    assert status == 404
    assert payload["error_code"] == "TASK_LINEAGE_NOT_FOUND"
    assert payload["task_id"] == "task-missing"
    assert "traceback" not in payload


def test_task_lineage_probe_fails_closed_with_503_when_lineage_schema_is_unavailable(probe_server):
    api = probe_server(error=LineageProjectionSchemaError("Missing required column cti_events.causation_event_id"))

    status, payload, _ = _get(api, "/api/cti/tasks/task-292/lineage")

    assert status == 503
    assert payload["error_code"] == "LINEAGE_SCHEMA_UNAVAILABLE"
    assert payload["task_id"] == "task-292"
    assert "traceback" not in payload


def test_task_lineage_probe_rejects_blank_task_id_without_calling_projector(probe_server):
    api = probe_server(result=_projection())

    status, payload, _ = _get(api, "/api/cti/tasks/%20/lineage")

    assert status == 400
    assert payload["error_code"] == "INVALID_TASK_ID"
    assert api.orchestrator.requested_task_ids == []


def test_stage_2_9_2_control_version_and_interface_catalog_are_current():
    from cti_services.interface_catalog import provided_interfaces

    assert CtiSubsystemOrchestrator.CONTROL_VERSION == "hybrid-event-driven-2.17-health-diagnostics"
    interfaces = provided_interfaces(host="127.0.0.1", port=8765)
    assert any("GET /api/cti/tasks/{task_id}/lineage" in row.interface for row in interfaces)

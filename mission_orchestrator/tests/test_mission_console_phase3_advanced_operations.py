from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


def _service() -> CanonicalMissionService:
    root = Path(__file__).resolve().parents[1]
    return CanonicalMissionService(
        repository=MissionRepository(sqlite_path=str(root / "data" / "mission_orchestrator.db"))
    )


def _mission_with_two_plan_versions(service: CanonicalMissionService) -> str:
    for row in service.list_missions(limit=200)["missions"]:
        versions = service.repository.list_plan_versions(row["mission_id"])
        if len(versions) >= 2:
            return row["mission_id"]
    raise AssertionError("fixture database must contain a mission with at least two plan versions")


def test_phase3_console_surface_contains_all_advanced_operations():
    root = Path(__file__).resolve().parents[1]
    js = (root / "mission_web" / "app.js").read_text(encoding="utf-8")
    html = (root / "mission_web" / "index.html").read_text(encoding="utf-8")

    assert "PHASE 3 · ADVANCED OPERATIONS" in html
    assert "new EventSource" in js
    assert "/events/stream" in js
    assert "/plan-diff" in js
    assert "Causal Graph" in js
    assert "/evidence-browser" in js
    assert "/forensic-reconstruction" in js
    assert "/api/mission-comparison" in js
    assert "/api/operator/attention/advanced" in js
    # Phase 2 safety invariants remain present underneath Phase 3.
    assert "const PHASE2_COMMANDS = ['START', 'PAUSE', 'RESUME', 'REPLAN', 'BEGIN_CLEANUP', 'ABORT'];" in js
    assert "approval_decision_enabled" not in js


def test_phase3_plan_diff_and_event_snapshot_are_read_only():
    service = _service()
    mission_id = _mission_with_two_plan_versions(service)
    versions = service.repository.list_plan_versions(mission_id)
    before = int(versions[-2]["plan_version"])
    after = int(versions[-1]["plan_version"])

    diff = service.get_plan_version_diff(mission_id, from_version=before, to_version=after)
    assert diff["read_only"] is True
    assert diff["mission_id"] == mission_id
    assert diff["from"]["plan_version"] == before
    assert diff["to"]["plan_version"] == after
    assert diff["dispatch_performed"] is False
    assert diff["target_actuation"] is False
    assert set(diff["summary"]) >= {
        "plan_content_equal",
        "added_task_count",
        "removed_task_count",
        "modified_task_count",
    }

    snapshot = service.get_mission_event_stream_snapshot(mission_id, limit=3)
    assert snapshot["read_only"] is True
    assert snapshot["event_count"] <= 3
    assert snapshot["dispatch_performed"] is False
    assert snapshot["target_actuation"] is False
    if snapshot["events"]:
        cursor = snapshot["events"][-1]["event_id"]
        later = service.get_mission_event_stream_snapshot(mission_id, after_event_id=cursor, limit=3)
        assert later["cursor_found"] is True


def test_phase3_evidence_compare_and_attention_preserve_authority_boundaries():
    service = _service()
    missions = service.list_missions(limit=2)["missions"]
    assert len(missions) >= 2
    left, right = missions[0]["mission_id"], missions[1]["mission_id"]

    evidence = service.get_evidence_browser(left, limit=25)
    assert evidence["read_only"] is True
    assert evidence["governance_query_performed"] is False
    assert evidence["dispatch_performed"] is False
    assert evidence["target_actuation"] is False
    assert "category_counts" in evidence

    comparison = service.compare_missions(left, right)
    assert comparison["read_only"] is True
    assert comparison["left"]["mission_id"] == left
    assert comparison["right"]["mission_id"] == right
    assert comparison["governance_authorization_performed"] is False
    assert comparison["dispatch_performed"] is False
    assert comparison["target_actuation"] is False

    attention = service.get_operator_attention_advanced(limit=3)
    assert attention["read_only"] is True
    assert attention["governance_authorization_performed"] is False
    assert attention["dispatch_performed"] is False
    assert attention["target_actuation"] is False
    for item in attention["items"]:
        assert item["severity"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
        assert item["recommended_operator_action"]


def test_phase3_http_sse_once_and_read_only_endpoints(monkeypatch):
    monkeypatch.setenv("MISSION_HTTP_QUIET", "1")
    service = _service()
    mission_id = _mission_with_two_plan_versions(service)
    versions = service.repository.list_plan_versions(mission_id)
    from_version = int(versions[-2]["plan_version"])
    to_version = int(versions[-1]["plan_version"])

    class Handler(MissionOrchestratorHandler):
        pass

    Handler.service = service
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(
            base + f"/api/missions/{mission_id}/plan-diff?from={from_version}&to={to_version}",
            timeout=10,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert payload["read_only"] is True

        latest = service.get_mission_event_stream_snapshot(mission_id, limit=1)["latest_event_id"]
        with urllib.request.urlopen(
            base + f"/api/missions/{mission_id}/events/stream?after={latest}&once=1",
            timeout=10,
        ) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers.get_content_type() == "text/event-stream"
            assert "event: stream_ready" in body
            assert "event: stream_end" in body
            assert '"read_only":true' in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

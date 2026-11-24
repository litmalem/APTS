from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.observability_forensics import (
    HASH_DOMAIN, SCHEMA_VERSION, build_forensic_evidence_bundle,
    canonical_forensic_definition, forensic_query, reconstruct_forensic_mission,
    verify_forensic_evidence_bundle,
)
from mission_orchestrator.observability_trace import sha256_hex
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload


def _service(tmp_path, name="stage389"):
    path = tmp_path / "missions.db"
    service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(path)))
    mission_id = service.create_mission(payload(name))["canonical_identity"]["mission_id"]
    return path, service, mission_id


def _inputs(bundle):
    return {"mission_id": bundle["mission_id"], "trace_id": bundle["trace_id"],
            "trace_contract": bundle["trace_contract"], "diagnostics": bundle["diagnostics"],
            "sources": bundle["sources"], "records": bundle["records"]}


def test_complete_bundle_is_restart_stable_and_does_not_write(tmp_path):
    path, service, mission_id = _service(tmp_path)
    before = service.repository.list_mission_events(mission_id)
    first = service.get_forensic_evidence_bundle(mission_id)
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(path)))
    assert first == restarted.get_forensic_evidence_bundle(mission_id)
    assert before == service.repository.list_mission_events(mission_id)
    bundle = first["bundle"]
    assert first["integrity_status"] == "PASS" and bundle["status"] == "VERIFIED"
    assert bundle["records"]["mission_envelope"]["identity"]["mission_id"] == mission_id
    assert bundle["record_counts"]["mission_events"] == 1
    assert bundle["sources"]["timeline"]["event_count"] == 1
    assert bundle["diagnostics"]["status"] == "PASS"
    assert verify_forensic_evidence_bundle(bundle)


def test_state_transition_is_reconstructed_in_ledger_order(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-transition")
    state = service.get_mission_state(mission_id)["mission_state"]
    service.transition_mission_state(mission_id, {
        "expected_state_version": state["state_version"], "to_state": "PIP_BOUND",
        "actor": "forensic-test", "reason_code": "PIP_AVAILABLE", "reason": "test",
        "evidence_refs": [], "metadata": {},
    })
    reconstruction = service.get_forensic_reconstruction(mission_id)["result"]
    assert reconstruction["status"] == "VERIFIED"
    data = reconstruction["reconstruction"]
    assert data["ordering"] == "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER"
    assert data["mission_state"]["state"] == "PIP_BOUND"
    assert data["state_transitions"][-1]["to_state"] == "PIP_BOUND"
    assert data["event_count"] == len(service.repository.list_mission_events(mission_id))
    assert data["head_event_sha256"] == data["timeline"]["entries"][-1]["source_event_sha256"]
    assert reconstruction == reconstruct_forensic_mission(
        service.get_forensic_evidence_bundle(mission_id)["bundle"])


def test_forensic_event_and_lineage_query_select_exact_reference(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-query")
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    event_id = bundle["sources"]["normalized_events"][0]["source_event_id"]
    selected = forensic_query(bundle, scope="events", reference=event_id)
    assert selected["status"] == "VERIFIED"
    assert len(selected["result"]["events"]) == 1
    assert len(selected["result"]["timeline_entries"]) == 1
    assert forensic_query(bundle, scope="events", reference=event_id[:-2])["result"]["events"] == []
    assert forensic_query(bundle, scope="lineage")["result"]["causal_graph"]["node_count"] == 2
    ancestor_path = forensic_query(bundle, scope="lineage", reference=event_id)["result"]
    assert len(ancestor_path["nodes"]) == 2
    assert len(ancestor_path["timeline_entries"]) == 1
    assert forensic_query(bundle, scope="lineage", reference="missing")["result"]["nodes"] == []
    assert forensic_query(bundle, scope="tasks")["result"]["planned_tasks"] == []
    assert forensic_query(bundle, scope="execution")["result"]["execution_attempts"] == []
    with pytest.raises(ValueError, match="invalid forensic query"):
        forensic_query(bundle, scope="dispatch")


def test_tampered_bundle_and_rehashed_record_are_rejected_or_withheld(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-tamper")
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    tampered = deepcopy(bundle)
    tampered["sources"]["timeline"]["event_count"] = 17
    assert not verify_forensic_evidence_bundle(tampered)
    with pytest.raises(ValueError, match="unverified"):
        reconstruct_forensic_mission(tampered)
    records = deepcopy(bundle["records"])
    records["route_decisions"].append({"mission_id": mission_id, "route_decision_id": "fake"})
    withheld = build_forensic_evidence_bundle(**{**_inputs(bundle), "records": records})
    assert withheld["status"] == "WITHHELD"
    assert withheld["reason_code"] == "DECISION_EVIDENCE_BINDING_MISMATCH"
    assert withheld["records"] is None and withheld["sources"] is None
    assert verify_forensic_evidence_bundle(withheld)


def test_evidence_manifest_reference_mismatch_withholds_bundle(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-evidence")
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    records = deepcopy(bundle["records"])
    records["evidence_binding_verifications"].append({
        "mission_id": mission_id, "result_capture_id": "xresult-missing",
        "task_evidence_binding_verification_contract": {}, "canonical_sha256": "0" * 64,
    })
    withheld = build_forensic_evidence_bundle(**{**_inputs(bundle), "records": records})
    assert withheld["status"] == "WITHHELD"
    assert withheld["reason_code"] == "EVIDENCE_BINDING_MISMATCH"


def test_diagnostic_unavailable_withholds_reconstruction_and_records(tmp_path, monkeypatch):
    _, service, mission_id = _service(tmp_path, "stage389-unavailable")
    def broken(_mission_id):
        raise ValueError("graph unavailable")
    monkeypatch.setattr(service, "get_global_causal_lineage_graph", broken)
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    assert bundle["status"] == "WITHHELD"
    assert bundle["reason_code"] == "OBSERVABILITY_INDETERMINATE"
    assert bundle["diagnostics"]["source_status"]["causal_graph"] == "UNAVAILABLE"
    assert bundle["records"] is None and bundle["sources"] is None
    assert service.get_forensic_reconstruction(mission_id)["result"]["reconstruction"] is None
    query = service.query_forensic_mission(mission_id, scope="evidence")["result"]
    assert query["status"] == "WITHHELD" and query["result"] is None


def test_record_snapshot_drift_is_withheld(tmp_path, monkeypatch):
    _, service, mission_id = _service(tmp_path, "stage389-drift")
    original = service.repository.list_state_transitions
    reads = 0
    def drift(mid):
        nonlocal reads
        reads += 1
        value = original(mid)
        return value if reads == 1 else [{"mission_id": mid, "unexpected": True}]
    monkeypatch.setattr(service.repository, "list_state_transitions", drift)
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    assert bundle["status"] == "WITHHELD"
    assert bundle["reason_code"] == "RECORD_SNAPSHOT_DRIFT"
    assert bundle["records"] is None


def test_rehashed_state_and_event_inconsistency_cannot_pass(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-state")
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    records = deepcopy(bundle["records"])
    records["mission_state"]["state_version"] = 27
    withheld = build_forensic_evidence_bundle(**{**_inputs(bundle), "records": records})
    assert withheld["reason_code"] == "STATE_HISTORY_MISMATCH"
    rehashed = deepcopy(bundle)
    rehashed["records"]["mission_events"][0]["event_type"] = "ALTERED"
    core = dict(rehashed)
    core.pop("integrity")
    rehashed["integrity"]["canonical_sha256"] = sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
    assert not verify_forensic_evidence_bundle(rehashed)


def test_contract_health_unknown_mission_and_invalid_scope(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-contract")
    assert service.get_forensic_contract_definition()["definition"] == canonical_forensic_definition()
    health = service.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][-13:] == [
        "stage3.8.8-observability-metrics-health-operator-diagnostics",
        "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api",
        "stage3.8.10-observe-reconstruct-acceptance-regression-gate",
        "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract",
        "stage3.9.2-intake-lifecycle-e2e-segment-qualification",
        "stage3.9.3-planning-task-graph-dependency-verification",
        "stage3.9.4-routing-delegation-governance-continuity",
        "stage3.9.5-dispatch-execution-evidence-continuity",
        "stage3.9.6-task-completion-mission-outcome-closure",
        "stage3.9.7-adaptation-replanning-e2e-scenario",
        "stage3.9.8-restart-replay-recovery-e2e-verification",
        "stage3.9.9-global-observation-reconstruction-forensic-equivalence",
        "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == 53
    assert health["forensic_query_evidence_bundle_schema_version"] == SCHEMA_VERSION
    assert health["forensic_query_evidence_bundle_read_only"] is True
    assert health["forensic_query_evidence_bundle_new_durable_store_added"] is False
    assert service.get_observability_metrics_health(mission_id)["report"]["observability_health"]["status"] == "HEALTHY"
    with pytest.raises(MissionNotFound):
        service.get_forensic_evidence_bundle("mission-missing")


def test_http_routes_query_validation_and_not_found(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage389-http")
    handler = type("ForensicHandler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/observability/forensic-contract") as response:
            assert json.load(response)["definition"]["schema_version"] == SCHEMA_VERSION
        prefix = base + f"/api/missions/{mission_id}"
        with urlopen(prefix + "/forensic-evidence-bundle") as response:
            assert json.load(response)["bundle"]["status"] == "VERIFIED"
        with urlopen(prefix + "/forensic-reconstruction") as response:
            assert json.load(response)["result"]["reconstruction"]["event_count"] == 1
        with urlopen(prefix + "/forensic-query?scope=events") as response:
            assert len(json.load(response)["result"]["result"]["events"]) == 1
        for query in ("", "?scope=unknown", "?scope=events&scope=tasks", "?scope=events&extra=1",
                      "?scope=events&broken"):
            with pytest.raises(HTTPError) as exc:
                urlopen(prefix + "/forensic-query" + query)
            assert exc.value.code == 400
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/api/missions/mission-missing/forensic-evidence-bundle")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

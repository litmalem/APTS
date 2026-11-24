from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_observation_reconstruction_forensic_equivalence import (
    OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES,
    OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL,
    OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_NONZERO_COUNTS,
    OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL,
    OBSERVATION_RECONSTRUCTION_FORENSIC_REQUIRED_SOURCES,
    OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
    canonical_observation_reconstruction_forensic_contract,
    evaluate_observation_reconstruction_forensic_equivalence,
    verify_observation_reconstruction_forensic_contract,
)
from mission_orchestrator.observability_forensics import (
    forensic_query,
    reconstruct_forensic_mission,
    verify_forensic_evidence_bundle,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_9_8_restart_replay_recovery_e2e_verification import provision as provision_stage398

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def _views(service: CanonicalMissionService, mission_id: str):
    event_view = service.get_mission_events(mission_id)
    try:
        repository_integrity = service.get_mission_repository(mission_id)["integrity_status"]
    except Exception:
        repository_integrity = "FAIL"
    return {
        "mission_id": mission_id,
        "predecessor_qualification": service.get_e2e_restart_replay_recovery_qualification(mission_id)["qualification"],
        "state": service.repository.get_state(mission_id),
        "active_plan": service.repository.get_active_plan_version(mission_id),
        "events": event_view["events"],
        "repository_counts": service.repository.get_repository_record_counts(mission_id),
        "event_integrity_status": event_view["integrity_status"],
        "repository_integrity_status": repository_integrity,
        "trace_view": service.get_observability_trace_identity(mission_id),
        "normalized_view": service.get_normalized_observability_events(mission_id),
        "causal_view": service.get_global_causal_lineage_graph(mission_id),
        "live_view": service.get_live_mission_state_execution_projection(mission_id),
        "decision_view": service.get_decision_governance_evidence_trace(mission_id),
        "timeline_view": service.get_deterministic_mission_timeline(mission_id),
        "diagnostics_view": service.get_integrity_gap_consistency_diagnostics(mission_id),
        "metrics_view": service.get_observability_metrics_health(mission_id),
        "forensic_bundle": service.get_forensic_evidence_bundle(mission_id)["bundle"],
        "forensic_reconstruction": service.get_forensic_reconstruction(mission_id)["result"],
        "forensic_events_query": service.query_forensic_mission(mission_id, scope="events")["result"],
        "forensic_lineage_query": service.query_forensic_mission(mission_id, scope="lineage")["result"],
        "forensic_integrity_query": service.query_forensic_mission(mission_id, scope="integrity")["result"],
    }


@pytest.fixture(scope="module")
def shared_context(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("stage399-shared")
    service, restarted, governance, runtime, mission_id, rows, body, checkpoint, before = provision_stage398(
        tmp_path, "shared399"
    )
    views = _views(restarted, mission_id)
    before_read_only = {
        "events": restarted.get_mission_events(mission_id),
        "counts": restarted.repository.get_repository_record_counts(mission_id),
        "state": restarted.get_mission_state(mission_id),
        "calls": (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls),
    }
    service_proof = restarted.get_e2e_observation_reconstruction_forensic_equivalence(mission_id)
    after_read_only = {
        "events": restarted.get_mission_events(mission_id),
        "counts": restarted.repository.get_repository_record_counts(mission_id),
        "state": restarted.get_mission_state(mission_id),
        "calls": (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls),
    }
    return {
        "service": service,
        "restarted": restarted,
        "governance": governance,
        "runtime": runtime,
        "mission_id": mission_id,
        "rows": rows,
        "body": body,
        "checkpoint": checkpoint,
        "before": before,
        "proof": service_proof,
        "views": views,
        "before_read_only": before_read_only,
        "after_read_only": after_read_only,
    }


def test_01_contract_binds_398_and_advances_to_3910():
    contract = canonical_observation_reconstruction_forensic_contract()
    assert verify_observation_reconstruction_forensic_contract(contract)
    assert contract["predecessor_control"] == OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL
    assert contract["qualified_observation_head"]["mission_event_count"] == 50
    assert contract["qualified_observation_head"]["causal_node_count"] == 51
    assert contract["qualified_observation_head"]["equivalence_status"] == "PASS"
    assert contract["next_stage"] == "3.9.10"
    forged = deepcopy(contract)
    forged["qualified_observation_head"]["timeline_event_count"] = 49
    assert verify_observation_reconstruction_forensic_contract(forged) is False


def test_02_health_activates_399_without_new_persistence_or_authority(shared_context):
    health = shared_context["restarted"].health()
    assert health["control_version"] == CONTROL
    assert health["supported_controls"][-3:] == [OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL, "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CONTROL]
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL == 53
    assert health["stage3_9_9_observation_reconstruction_forensic_schema_version"] == OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION
    assert health["stage3_9_9_runtime_verifier_read_only"] is True
    assert health["stage3_9_9_forensic_equivalence_required"] is True
    assert health["stage3_9_9_required_observability_sources"] == list(OBSERVATION_RECONSTRUCTION_FORENSIC_REQUIRED_SOURCES)
    assert health["stage3_9_9_new_database_migration_added"] is False
    assert health["stage3_9_9_new_durable_store_added"] is False
    assert health["stage3_9_9_new_observation_authority_added"] is False
    assert health["stage3_9_9_new_forensic_authority_added"] is False
    assert health["stage3_9_9_target_actuation"] is False
    assert health["stage3_9_9_next_stage"] == "3.9.10"


def test_03_canonical_stage398_head_qualifies_global_equivalence(shared_context):
    proof = shared_context["proof"]
    assert proof["qualification"]["status"] == "QUALIFIED", proof["qualification"]["failed_check_ids"]
    head = proof["qualification"]["segment_head"]
    assert head["state"] == "RUNNING" and head["state_version"] == 4
    assert head["active_plan_version"] == 2
    assert head["event_count"] == head["normalized_event_count"] == head["timeline_event_count"] == 50
    assert head["causal_node_count"] == 51 and head["causal_edge_count"] == 50
    assert head["diagnostics_status"] == "PASS"
    assert head["observability_health"] == "HEALTHY"
    assert head["forensic_bundle_status"] == head["forensic_reconstruction_status"] == head["forensic_query_status"] == "VERIFIED"
    assert head["equivalence_status"] == "PASS"


def test_04_raw_normalized_timeline_event_references_are_exact(shared_context):
    views = shared_context["views"]
    raw = [(x["event_id"], x["canonical_sha256"], x["event_type"]) for x in views["events"]]
    normalized = [(x["source_event_id"], x["source_event_sha256"], x["event_type"]) for x in views["normalized_view"]["events"]]
    timeline = [(x["source_event_id"], x["source_event_sha256"], x["event_type"]) for x in views["timeline_view"]["timeline"]["entries"]]
    assert raw == normalized == timeline
    assert [x[2] for x in raw] == list(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES)
    assert len(raw) == 50


def test_05_direct_observability_views_equal_forensic_bundle_sources(shared_context):
    views = shared_context["views"]
    bundle = views["forensic_bundle"]
    assert verify_forensic_evidence_bundle(bundle)
    assert bundle["status"] == "VERIFIED"
    assert bundle["sources"]["normalized_events"] == views["normalized_view"]["events"]
    assert bundle["sources"]["causal_graph"] == views["causal_view"]["graph"]
    assert bundle["sources"]["decision_trace"] == views["decision_view"]["projection"]
    assert bundle["sources"]["timeline"] == views["timeline_view"]["timeline"]
    assert bundle["sources"]["live_projection"] == views["live_view"]["projection"]
    assert bundle["diagnostics"] == views["diagnostics_view"]["diagnostics"]


def test_06_forensic_bundle_records_bind_exact_durable_event_state_and_plan(shared_context):
    views = shared_context["views"]
    bundle = views["forensic_bundle"]
    assert bundle["records"]["mission_events"] == views["events"]
    assert bundle["records"]["mission_state"] == views["state"]
    assert bundle["records"]["active_plan_version"] == views["active_plan"]
    assert bundle["record_counts"]["mission_events"] == 50
    assert {k: v for k, v in views["repository_counts"].items() if v} == OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_NONZERO_COUNTS


def test_07_reconstruction_is_exact_bundle_derivation_and_preserves_canonical_head(shared_context):
    views = shared_context["views"]
    reconstruction = views["forensic_reconstruction"]
    assert reconstruction["status"] == "VERIFIED"
    assert reconstruction == reconstruct_forensic_mission(views["forensic_bundle"])
    data = reconstruction["reconstruction"]
    assert data["timeline"] == views["timeline_view"]["timeline"]
    assert data["causal_graph"] == views["causal_view"]["graph"]
    assert data["decision_trace"] == views["decision_view"]["projection"]
    assert data["live_projection"] == views["live_view"]["projection"]
    assert data["mission_state"] == views["state"]
    assert data["active_plan_version"] == views["active_plan"]
    assert data["head_event_sha256"] == views["events"][-1]["canonical_sha256"]


def test_08_forensic_queries_are_exact_bundle_slices(shared_context):
    views = shared_context["views"]
    bundle = views["forensic_bundle"]
    assert views["forensic_events_query"] == forensic_query(bundle, scope="events")
    assert views["forensic_lineage_query"] == forensic_query(bundle, scope="lineage")
    assert views["forensic_integrity_query"] == forensic_query(bundle, scope="integrity")
    assert len(views["forensic_events_query"]["result"]["events"]) == 50
    assert len(views["forensic_events_query"]["result"]["timeline_entries"]) == 50
    assert views["forensic_lineage_query"]["result"]["causal_graph"] == views["causal_view"]["graph"]
    assert views["forensic_integrity_query"]["result"]["diagnostics"]["status"] == "PASS"


def test_09_global_trace_and_tip_hash_are_identical_across_all_views(shared_context):
    views = shared_context["views"]
    trace_id = views["trace_view"]["trace_id"]
    assert all(x == trace_id for x in (
        views["normalized_view"]["trace_id"], views["causal_view"]["trace_id"],
        views["live_view"]["trace_id"], views["decision_view"]["trace_id"],
        views["timeline_view"]["trace_id"], views["diagnostics_view"]["trace_id"],
        views["forensic_bundle"]["trace_id"],
    ))
    tip = views["events"][-1]["canonical_sha256"]
    assert views["normalized_view"]["events"][-1]["source_event_sha256"] == tip
    assert views["timeline_view"]["timeline"]["entries"][-1]["source_event_sha256"] == tip
    assert views["forensic_reconstruction"]["reconstruction"]["head_event_sha256"] == tip


def test_10_equivalence_is_restart_stable_for_same_durable_repository(shared_context):
    service = shared_context["service"]
    mission_id = shared_context["mission_id"]
    assert service.get_forensic_evidence_bundle(mission_id)["bundle"] == shared_context["views"]["forensic_bundle"]
    assert service.get_forensic_reconstruction(mission_id)["result"] == shared_context["views"]["forensic_reconstruction"]


def test_11_qualification_is_read_only_and_durable_state_is_unchanged(shared_context):
    before = shared_context["before_read_only"]
    after = shared_context["after_read_only"]
    assert shared_context["proof"]["qualification"]["qualified"] is True
    assert after["events"] == before["events"]
    assert after["counts"] == before["counts"]
    assert after["state"] == before["state"]


def test_12_qualification_performs_no_governance_runtime_dispatch_or_actuation(shared_context):
    proof = shared_context["proof"]
    before = shared_context["before_read_only"]["calls"]
    assert proof["read_only"] is True
    assert proof["governance_query_performed"] is False
    assert proof["runtime_query_performed"] is False
    assert proof["routing_performed"] is False
    assert proof["delegation_performed"] is False
    assert proof["dispatch_performed"] is False
    assert proof["new_execution_attempt_created"] is False
    assert proof["mission_state_transition_performed"] is False
    assert proof["integrity_repair_performed"] is False
    assert proof["telemetry_export_performed"] is False
    assert proof["external_network_io_performed"] is False
    assert proof["target_actuation"] is False
    assert shared_context["after_read_only"]["calls"] == before


def test_13_cross_view_source_drift_is_rejected_by_equivalence_evaluator(shared_context):
    inputs = deepcopy(shared_context["views"])
    drifted = deepcopy(inputs["normalized_view"])
    drifted["events"] = drifted["events"][:-1]
    drifted["event_count"] = len(drifted["events"])
    inputs["normalized_view"] = drifted
    result = evaluate_observation_reconstruction_forensic_equivalence(**inputs)
    assert result["status"] == "REJECTED"
    assert result["qualified"] is False
    assert "RAW_NORMALIZED_TIMELINE_EVENT_EQUIVALENCE" in result["failed_check_ids"]
    assert "DIRECT_OBSERVABILITY_VIEWS_EQUAL_FORENSIC_SOURCES" in result["failed_check_ids"]


def test_14_canonical_event_tamper_fails_closed_before_forensic_equivalence(tmp_path):
    service, _, _, _, mission_id, _, _, _, _ = provision_stage398(tmp_path, "tamper399")
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_events SET canonical_sha256=? WHERE id=(SELECT MAX(id) FROM mission_events WHERE mission_id=?)",
            ("0" * 64, mission_id),
        )
        conn.commit()
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(service.repository.sqlite_path))
    )
    with pytest.raises(Exception):
        restarted.get_e2e_observation_reconstruction_forensic_equivalence(mission_id)


def test_15_http_contract_and_equivalence_routes(shared_context):
    service = shared_context["restarted"]
    mission_id = shared_context["mission_id"]
    handler = type("Stage399Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/e2e/observation-reconstruction-forensic-equivalence-contract") as resp:
            contract = json.loads(resp.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-observation-reconstruction-forensic-equivalence") as resp:
            proof = json.loads(resp.read().decode("utf-8"))
        assert contract["definition"]["schema_version"] == OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION
        assert contract["definition"]["mission_event_count_expected"] == 50
        assert contract["definition"]["next_stage"] == "3.9.10"
        assert proof["qualification"]["status"] == "QUALIFIED"
        assert proof["qualification"]["segment_head"]["equivalence_status"] == "PASS"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

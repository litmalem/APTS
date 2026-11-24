from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from mission_orchestrator.observability_causal_graph import build_global_causal_lineage_graph
from mission_orchestrator.observability_decision_trace import (
    HASH_DOMAIN as DECISION_HASH_DOMAIN, build_decision_governance_evidence_trace,
)
from mission_orchestrator.observability_diagnostics import (
    SCHEMA_VERSION, build_integrity_gap_consistency_diagnostics,
    canonical_integrity_gap_consistency_diagnostics_definition,
    verify_integrity_gap_consistency_diagnostics,
)
from mission_orchestrator.observability_live_projection import build_live_mission_state_execution_projection
from mission_orchestrator.observability_timeline import build_deterministic_mission_timeline
from mission_orchestrator.observability_trace import sha256_hex
from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import MissionEventIntegrityError
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload
from tests.test_stage3_8_6_deterministic_mission_timeline_reconstruction import _sources


def _service(tmp_path, key="stage387"):
    db = tmp_path / "missions.db"
    service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mid = service.create_mission(payload(key))["canonical_identity"]["mission_id"]
    return db, service, mid


def _inputs(count=4):
    first = datetime(2026, 9, 24, tzinfo=timezone.utc)
    normalized, graph, decision = _sources([
        (first + timedelta(seconds=index)).isoformat() for index in range(count)
    ])
    timeline = build_deterministic_mission_timeline(
        mission_id="mission-synthetic", trace_id="trace-synthetic",
        normalized_events=normalized, causal_graph=graph, decision_trace=decision)
    extras = {key: [] for key in (
        "plan_versions", "planned_tasks", "readiness_projections", "route_decisions",
        "delegations", "execution_dispatches", "execution_attempts", "running_projections",
        "result_captures", "termination_controls", "task_outcomes", "task_completions",
        "adaptation_episodes", "replan_commits",
    )}
    live = build_live_mission_state_execution_projection(
        mission_id="mission-synthetic", trace_id="trace-synthetic",
        mission_state={"state": "DRAFT", "state_version": 1},
        normalized_events=normalized, causal_graph=graph, **extras)
    return {"mission_id": "mission-synthetic", "trace_id": "trace-synthetic",
            "normalized_events": normalized, "causal_graph": graph,
            "decision_trace": decision, "timeline": timeline, "live_projection": live}


def _codes(report):
    return {finding["code"] for finding in report["findings"]}


def test_real_mission_report_is_restart_stable_and_does_not_write(tmp_path):
    db, service, mid = _service(tmp_path)
    before = service.repository.list_mission_events(mid)
    result = service.get_integrity_gap_consistency_diagnostics(mid)
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    assert result == restarted.get_integrity_gap_consistency_diagnostics(mid)
    assert service.repository.list_mission_events(mid) == before
    assert result["integrity_status"] == "PASS"
    assert result["diagnostics"]["status"] == "PASS"
    assert result["diagnostics"]["blocking_finding_count"] == 0
    assert verify_integrity_gap_consistency_diagnostics(result["diagnostics"])


def test_backward_clock_and_external_causation_are_observations():
    sources = _inputs()
    # The synthetic source has an unresolved external reference from event 1.
    report = build_integrity_gap_consistency_diagnostics(**sources)
    assert report["status"] == "PASS"
    assert "UNRESOLVED_EXTERNAL_CAUSATION" in _codes(report)
    assert report["blocking_finding_count"] == 0
    mutated = deepcopy(sources)
    event = mutated["normalized_events"][-1]
    # Timestamp observation for an otherwise valid ledger is tested by rebuilding all sources.
    event["occurred_at_utc"] = "2026-09-24T00:00:00.000000Z"
    core = dict(event)
    core.pop("integrity")
    from mission_orchestrator.observability_ingestion import HASH_DOMAIN as EVENT_DOMAIN
    event["integrity"]["canonical_sha256"] = sha256_hex({"hash_domain": EVENT_DOMAIN, "core": core})
    graph = build_global_causal_lineage_graph(mission_id=sources["mission_id"], trace_id=sources["trace_id"],
                                              normalized_events=mutated["normalized_events"])
    decision = build_decision_governance_evidence_trace(mission_id=sources["mission_id"],
        trace_id=sources["trace_id"], normalized_events=mutated["normalized_events"],
        causal_graph=graph, sources={})
    mutated.update(causal_graph=graph, decision_trace=decision)
    mutated["timeline"] = build_deterministic_mission_timeline(mission_id=sources["mission_id"],
        trace_id=sources["trace_id"], normalized_events=mutated["normalized_events"],
        causal_graph=graph, decision_trace=decision)
    live_core = dict(mutated["live_projection"])
    live_core.pop("integrity")
    live_core["causal_head"]["graph_sha256"] = graph["integrity"]["canonical_sha256"]
    from mission_orchestrator.observability_live_projection import HASH_DOMAIN as LIVE_DOMAIN
    mutated["live_projection"]["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": LIVE_DOMAIN, "core": live_core})
    report = build_integrity_gap_consistency_diagnostics(**mutated)
    assert "OBSERVED_TIMESTAMP_BACKWARD" in _codes(report)
    assert report["status"] == "PASS"
    assert verify_integrity_gap_consistency_diagnostics(report)


def test_missing_parent_and_unavailable_derivatives_remain_indeterminate():
    sources = _inputs()
    empty_report = build_integrity_gap_consistency_diagnostics(**{
        **sources, "normalized_events": []})
    assert "MISSING_REGISTRATION_EVENT" in _codes(empty_report)
    broken = deepcopy(sources)
    event = broken["normalized_events"][1]
    event["parent_event_id"] = "mevent-lost"
    core = dict(event)
    core.pop("integrity")
    from mission_orchestrator.observability_ingestion import HASH_DOMAIN as EVENT_DOMAIN
    event["integrity"]["canonical_sha256"] = sha256_hex({"hash_domain": EVENT_DOMAIN, "core": core})
    broken.update(causal_graph=None, decision_trace=None, timeline=None, live_projection=None)
    report = build_integrity_gap_consistency_diagnostics(**broken,
        source_errors={"causal_graph": "ValueError", "decision_trace": "CAUSAL_GRAPH_UNAVAILABLE",
                       "timeline": "CAUSAL_GRAPH_UNAVAILABLE", "live_projection": "CAUSAL_GRAPH_UNAVAILABLE"})
    assert report["status"] == "INDETERMINATE"
    assert "MISSING_PARENT_EVENT" in _codes(report)
    assert report["source_status"]["causal_graph"] == "UNAVAILABLE"


def test_missing_causal_node_and_timeline_entry_are_reported():
    sources = _inputs()
    partial = sources["normalized_events"][:-1]
    graph = build_global_causal_lineage_graph(mission_id=sources["mission_id"],
        trace_id=sources["trace_id"], normalized_events=partial)
    decision = build_decision_governance_evidence_trace(mission_id=sources["mission_id"],
        trace_id=sources["trace_id"], normalized_events=partial, causal_graph=graph, sources={})
    timeline = build_deterministic_mission_timeline(mission_id=sources["mission_id"],
        trace_id=sources["trace_id"], normalized_events=partial, causal_graph=graph,
        decision_trace=decision)
    report = build_integrity_gap_consistency_diagnostics(**{**sources,
        "causal_graph": graph, "decision_trace": decision, "timeline": timeline})
    assert report["status"] == "FINDINGS"
    assert {"MISSING_CAUSAL_NODE", "MISSING_TIMELINE_EVENT", "GRAPH_LEDGER_DIVERGENCE",
            "TIMELINE_LEDGER_DIVERGENCE"} <= _codes(report)
    assert report["source_status"]["causal_graph"] == "PASS"  # Valid hash, wrong source snapshot.


def test_rehashed_decision_gap_and_live_mismatch_are_detected():
    sources = _inputs()
    decision = deepcopy(sources["decision_trace"])
    decision["entries"].pop()
    core = dict(decision)
    core.pop("integrity")
    decision["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": DECISION_HASH_DOMAIN, "core": core})
    live = deepcopy(sources["live_projection"])
    live["source_counts"]["normalized_event_count"] += 1
    live_core = dict(live)
    live_core.pop("integrity")
    from mission_orchestrator.observability_live_projection import HASH_DOMAIN as LIVE_DOMAIN
    live["integrity"]["canonical_sha256"] = sha256_hex({"hash_domain": LIVE_DOMAIN, "core": live_core})
    report = build_integrity_gap_consistency_diagnostics(**{
        **sources, "decision_trace": decision, "live_projection": live})
    assert "MISSING_DECISION_ANNOTATION" in _codes(report)
    assert "DECISION_LEDGER_DIVERGENCE" in _codes(report)
    assert "TIMELINE_DECISION_BINDING_MISMATCH" in _codes(report)
    assert "LIVE_LEDGER_DIVERGENCE" in _codes(report)


def test_invalid_source_hash_is_not_promoted_and_report_tampering_fails():
    sources = _inputs()
    sources["normalized_events"][0]["event_type"] = "UNVERIFIED"
    report = build_integrity_gap_consistency_diagnostics(**sources)
    assert report["status"] == "FINDINGS"
    assert report["source_status"]["normalized_events"] == "FAIL"
    assert "SOURCE_INTEGRITY_FAILED" in _codes(report)
    assert "MISSING_CAUSAL_NODE" not in _codes(report)
    tampered = deepcopy(report)
    tampered["findings"].clear()
    assert not verify_integrity_gap_consistency_diagnostics(tampered)


def test_rehashed_timeline_detail_mismatch_and_malformed_trace_fail_safely():
    sources = _inputs()
    timeline = deepcopy(sources["timeline"])
    timeline["entries"][1]["event_type"] = "MISLABELLED"
    from mission_orchestrator.observability_timeline import (
        HASH_DOMAIN as TIMELINE_DOMAIN, ENTRY_HASH_DOMAIN,
    )
    entry = timeline["entries"][1]
    entry_core = dict(entry)
    entry_core.pop("integrity")
    entry["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": ENTRY_HASH_DOMAIN, "core": entry_core})
    timeline_core = dict(timeline)
    timeline_core.pop("integrity")
    timeline["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": TIMELINE_DOMAIN, "core": timeline_core})
    report = build_integrity_gap_consistency_diagnostics(**{**sources, "timeline": timeline})
    assert report["source_status"]["timeline"] == "PASS"
    assert "TIMELINE_LEDGER_DIVERGENCE" in _codes(report)

    timeline = deepcopy(sources["timeline"])
    timeline["entries"][1]["decision_trace_categories"] = ["UNSUPPORTED"]
    entry = timeline["entries"][1]
    entry_core = dict(entry)
    entry_core.pop("integrity")
    entry["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": ENTRY_HASH_DOMAIN, "core": entry_core})
    timeline_core = dict(timeline)
    timeline_core.pop("integrity")
    timeline["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": TIMELINE_DOMAIN, "core": timeline_core})
    report = build_integrity_gap_consistency_diagnostics(**{**sources, "timeline": timeline})
    assert report["source_status"]["timeline"] == "PASS"
    assert "TIMELINE_SOURCE_DIVERGENCE" in _codes(report)

    decision = deepcopy(sources["decision_trace"])
    decision.pop("source_counts")
    decision_core = dict(decision)
    decision_core.pop("integrity")
    decision["integrity"]["canonical_sha256"] = sha256_hex(
        {"hash_domain": DECISION_HASH_DOMAIN, "core": decision_core})
    report = build_integrity_gap_consistency_diagnostics(**{**sources, "decision_trace": decision})
    assert report["source_status"]["decision_trace"] == "FAIL"
    assert "SOURCE_INTEGRITY_FAILED" in _codes(report)


def test_service_reports_source_failure_without_misreporting_pass(tmp_path, monkeypatch):
    _, service, mid = _service(tmp_path, "stage387-error")
    def broken_graph(_mission_id):
        raise ValueError("missing parent")
    monkeypatch.setattr(service, "get_global_causal_lineage_graph", broken_graph)
    report = service.get_integrity_gap_consistency_diagnostics(mid)["diagnostics"]
    assert report["status"] == "INDETERMINATE"
    assert report["source_status"]["causal_graph"] == "UNAVAILABLE"
    assert report["source_errors"]["causal_graph"] == "ValueError"
    assert verify_integrity_gap_consistency_diagnostics(report)


def test_corrupt_ledger_causes_indeterminate_diagnostic(tmp_path, monkeypatch):
    _, service, mid = _service(tmp_path, "stage387-ledger")
    def corrupt_ledger(_mission_id):
        raise MissionEventIntegrityError("integrity failure")
    monkeypatch.setattr(service, "get_normalized_observability_events", corrupt_ledger)
    report = service.get_integrity_gap_consistency_diagnostics(mid)["diagnostics"]
    assert report["status"] == "INDETERMINATE"
    assert set(report["source_status"].values()) == {"UNAVAILABLE"}
    assert report["source_errors"]["normalized_events"] == "MissionEventIntegrityError"


def test_http_routes_contract_existing_mission_and_not_found(tmp_path):
    _, service, mid = _service(tmp_path, "stage387-http")
    handler = type("DiagnosticsHandler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/observability/diagnostics-contract") as response:
            assert response.status == 200
            assert json.load(response)["definition"]["schema_version"] == SCHEMA_VERSION
        with urlopen(base + f"/api/missions/{mid}/observability-diagnostics") as response:
            assert response.status == 200
            assert json.load(response)["diagnostics"]["status"] == "PASS"
        with pytest.raises(HTTPError) as exc:
            urlopen(base + "/api/missions/mission-missing/observability-diagnostics")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_contract_health_and_unknown_mission(tmp_path):
    _, service, _ = _service(tmp_path, "stage387-contract")
    with pytest.raises(MissionNotFound):
        service.get_integrity_gap_consistency_diagnostics("mission-missing")
    definition = service.get_integrity_gap_consistency_diagnostics_contract_definition()["definition"]
    assert definition == canonical_integrity_gap_consistency_diagnostics_definition()
    assert definition["schema_version"] == SCHEMA_VERSION
    assert definition["runtime_side_effects"] is False
    health = service.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][-15:] == [
        "stage3.8.6-deterministic-mission-timeline-reconstruction",
        "stage3.8.7-integrity-gap-consistency-diagnostics",
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
        "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == 53
    assert health["integrity_gap_consistency_diagnostics_schema_version"] == SCHEMA_VERSION
    assert health["integrity_gap_consistency_diagnostics_read_only"] is True
    assert health["integrity_gap_consistency_diagnostics_new_durable_store_added"] is False

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from mission_orchestrator.observability_causal_graph import build_global_causal_lineage_graph
from mission_orchestrator.observability_decision_trace import build_decision_governance_evidence_trace
from mission_orchestrator.observability_ingestion import normalize_events
from mission_orchestrator.observability_timeline import (
    SCHEMA_VERSION, build_deterministic_mission_timeline,
    canonical_deterministic_mission_timeline_definition,
    verify_deterministic_mission_timeline,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService, MissionNotFound
from tests.test_stage3_1_1_identity_envelope import payload


def _service(tmp_path, key="stage386"):
    db = tmp_path / "mission.db"
    svc = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mission_id = svc.create_mission(payload(key))["canonical_identity"]["mission_id"]
    return db, svc, mission_id


def _sources(timestamps):
    """Build valid normalized projections with equal and decreasing source clocks."""
    event_types = (
        "MISSION_REGISTERED", "MISSION_TASK_ROUTE_DECISION_RECORDED",
        "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED",
        "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED",
    )
    raw = []
    for index, occurred in enumerate(timestamps):
        raw.append({
            "mission_id": "mission-synthetic", "event_id": f"mevent-{index}",
            "canonical_sha256": f"{index + 1:064x}",
            "source_component": "APTS-MO01", "event_type": event_types[index],
            "occurred_at": occurred, "correlation_id": "correlation-1",
            "causation_id": None if index == 0 else ("external-decision" if index == 1 else f"mevent-{index - 1}"),
            "parent_event_id": None if index == 0 else f"mevent-{index - 1}",
            "state_version": index + 1, "plan_version": None, "policy_version": "1",
        })
    normalized = normalize_events(raw, "mission-synthetic", "trace-synthetic")
    graph = build_global_causal_lineage_graph(
        mission_id="mission-synthetic", trace_id="trace-synthetic", normalized_events=normalized,
    )
    decisions = build_decision_governance_evidence_trace(
        mission_id="mission-synthetic", trace_id="trace-synthetic",
        normalized_events=normalized, causal_graph=graph, sources={},
    )
    return normalized, graph, decisions


def _timeline(normalized, graph, decisions):
    return build_deterministic_mission_timeline(
        mission_id="mission-synthetic", trace_id="trace-synthetic",
        normalized_events=normalized, causal_graph=graph, decision_trace=decisions,
    )


def test_real_mission_timeline_is_restart_stable_and_read_only(tmp_path):
    db, svc, mid = _service(tmp_path)
    before = svc.repository.list_mission_events(mid)
    first = svc.get_deterministic_mission_timeline(mid)
    second = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db))).get_deterministic_mission_timeline(mid)
    assert first == second
    assert svc.repository.list_mission_events(mid) == before
    timeline = first["timeline"]
    assert verify_deterministic_mission_timeline(timeline)
    assert timeline["event_count"] == len(before)
    assert [entry["source_event_id"] for entry in timeline["entries"]] == [event["event_id"] for event in before]
    assert timeline["causal_graph_id"] == svc.get_global_causal_lineage_graph(mid)["graph"]["graph_id"]
    assert timeline["decision_trace_id"] == svc.get_decision_governance_evidence_trace(mid)["projection"]["trace_projection_id"]


def test_equal_and_backward_timestamps_do_not_reorder_causes():
    a = datetime(2026, 9, 24, tzinfo=timezone.utc)
    values = [a, a + timedelta(seconds=2), a + timedelta(seconds=2), a + timedelta(seconds=1)]
    normalized, graph, decisions = _sources([value.isoformat() for value in values])
    timeline = _timeline(normalized, graph, decisions)
    entries = timeline["entries"]
    assert [entry["source_event_id"] for entry in entries] == [f"mevent-{i}" for i in range(4)]
    assert [entry["timestamp_relation_to_previous"] for entry in entries] == ["FIRST", "FORWARD", "SAME", "BACKWARD"]
    assert [entry["observed_delta_from_previous_us"] for entry in entries] == [None, 2_000_000, 0, -1_000_000]
    assert timeline["timestamp_anomalies"] == [{
        "sequence": 4, "source_event_id": "mevent-3",
        "type": "OBSERVED_TIMESTAMP_BACKWARD", "delta_us": -1_000_000,
    }]
    assert entries[1]["causation_resolution"] == "UNRESOLVED_EXTERNAL"
    assert entries[2]["causation_resolution"] == "RESOLVED_EVENT"
    assert entries[2]["causation_node_id"] == entries[1]["causal_node_id"]
    assert entries[1]["decision_trace_categories"] == ["DECISION"]
    assert "GOVERNANCE" in entries[2]["decision_trace_categories"]
    assert "EVIDENCE" in entries[3]["decision_trace_categories"]
    assert verify_deterministic_mission_timeline(timeline)


def test_cross_mission_and_source_tampering_fail_closed():
    normalized, graph, decisions = _sources(["2026-09-24T00:00:00Z"])
    with pytest.raises(ValueError, match="cross-mission"):
        build_deterministic_mission_timeline(mission_id="another", trace_id="trace-synthetic",
            normalized_events=normalized, causal_graph=graph, decision_trace=decisions)
    modified = deepcopy(normalized)
    modified[0]["event_type"] = "INVENTED"
    with pytest.raises(ValueError, match="normalized event integrity"):
        _timeline(modified, graph, decisions)
    invalid_graph = deepcopy(graph)
    invalid_graph["edges"][0]["relation_type"] = "INVENTED"
    with pytest.raises(ValueError, match="causal graph integrity"):
        _timeline(normalized, invalid_graph, decisions)
    invalid_decisions = deepcopy(decisions)
    invalid_decisions["causal_graph_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="decision trace integrity"):
        _timeline(normalized, graph, invalid_decisions)


def test_projection_detects_entry_and_order_mutations():
    normalized, graph, decisions = _sources([
        "2026-09-24T00:00:00Z", "2026-09-24T00:00:01Z",
    ])
    timeline = _timeline(normalized, graph, decisions)
    changed = deepcopy(timeline)
    changed["entries"][1]["source_event_sha256"] = "0" * 64
    assert not verify_deterministic_mission_timeline(changed)
    changed = deepcopy(timeline)
    changed["entries"].reverse()
    assert not verify_deterministic_mission_timeline(changed)
    changed = deepcopy(timeline)
    changed["timestamp_anomalies"].append({"sequence": 1})
    assert not verify_deterministic_mission_timeline(changed)


def test_unknown_mission_and_contract_and_health(tmp_path):
    _, svc, _ = _service(tmp_path, "stage386-health")
    with pytest.raises(MissionNotFound):
        svc.get_deterministic_mission_timeline("mission-missing")
    definition = svc.get_deterministic_mission_timeline_contract_definition()["definition"]
    assert definition == canonical_deterministic_mission_timeline_definition()
    assert definition["schema_version"] == SCHEMA_VERSION
    assert definition["runtime_side_effects"] is False
    health = svc.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][-16:] == [
        "stage3.8.5-decision-governance-evidence-trace",
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
    assert health["deterministic_mission_timeline_schema_version"] == SCHEMA_VERSION
    assert health["deterministic_mission_timeline_read_only"] is True
    assert health["deterministic_mission_timeline_new_durable_store_added"] is False

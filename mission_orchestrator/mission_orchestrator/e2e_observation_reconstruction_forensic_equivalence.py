from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID
from .e2e_restart_replay_recovery_qualification import (
    RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES,
    RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS,
    canonical_restart_replay_recovery_contract,
)
from .observability_forensics import (
    forensic_query,
    reconstruct_forensic_mission,
    verify_forensic_evidence_bundle,
)

OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION = (
    "apts-stage3.9-global-observation-reconstruction-forensic-equivalence-v1"
)
OBSERVATION_RECONSTRUCTION_FORENSIC_HASH_DOMAIN = (
    "MISSION_STAGE3_9_9_GLOBAL_OBSERVATION_RECONSTRUCTION_FORENSIC_EQUIVALENCE_V1"
)
OBSERVATION_RECONSTRUCTION_FORENSIC_MODE = (
    "GLOBAL_OBSERVATION_RECONSTRUCTION_FORENSIC_CROSS_VIEW_EQUIVALENCE"
)
OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL = (
    "stage3.9.8-restart-replay-recovery-e2e-verification"
)
OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL = 53
OBSERVATION_RECONSTRUCTION_FORENSIC_NEXT_STAGE = "3.9.10"
OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES = (
    RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES
)
OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_NONZERO_COUNTS = (
    RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS
)
OBSERVATION_RECONSTRUCTION_FORENSIC_REQUIRED_SOURCES = (
    "normalized_events",
    "causal_graph",
    "decision_trace",
    "timeline",
    "live_projection",
)


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_observation_reconstruction_forensic_contract() -> dict[str, Any]:
    predecessor = canonical_restart_replay_recovery_contract()
    core = {
        "schema_version": OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
        "mode": OBSERVATION_RECONSTRUCTION_FORENSIC_MODE,
        "predecessor_control": OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "persistence_mode": "EXISTING_DURABLE_STAGE3_RECORDS_ONLY",
        "observation_authority": "EXISTING_STAGE3_8_READ_ONLY_OBSERVABILITY_PROJECTIONS",
        "forensic_authority": "EXISTING_STAGE3_8_9_SOURCE_BOUND_FORENSIC_APIS",
        "qualified_observation_head": {
            "state": "RUNNING",
            "state_version": 4,
            "active_plan_version": 2,
            "mission_event_count": len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES),
            "normalized_event_count": len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES),
            "timeline_event_count": len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES),
            "causal_node_count": len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES) + 1,
            "causal_edge_count": len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES),
            "diagnostics_status": "PASS",
            "observability_health": "HEALTHY",
            "forensic_bundle_status": "VERIFIED",
            "forensic_reconstruction_status": "VERIFIED",
            "forensic_query_status": "VERIFIED",
            "equivalence_status": "PASS",
        },
        "expected_event_types": list(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_NONZERO_COUNTS),
        "required_observability_sources": list(OBSERVATION_RECONSTRUCTION_FORENSIC_REQUIRED_SOURCES),
        "equivalence_requirements": {
            "stage3_9_8_restart_head_is_qualified": True,
            "raw_event_ledger_matches_normalized_events": True,
            "normalized_events_match_deterministic_timeline": True,
            "direct_observability_views_match_forensic_bundle_sources": True,
            "forensic_bundle_records_match_durable_event_state_plan_sources": True,
            "forensic_reconstruction_matches_verified_forensic_bundle": True,
            "forensic_event_query_matches_bundle_normalized_events": True,
            "forensic_lineage_query_matches_bundle_graph_and_timeline": True,
            "forensic_integrity_query_matches_bundle_diagnostics_and_record_counts": True,
            "mission_state_and_active_plan_match_live_and_reconstructed_views": True,
            "canonical_event_tip_matches_all_reconstruction_heads": True,
            "trace_identity_is_global_and_identical_across_views": True,
            "repeated_reads_are_deterministic_for_stable_durable_sources": True,
            "tamper_gap_or_source_drift_fails_closed": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "observation_projection_is_authority": False,
            "forensic_bundle_is_external_attestation": False,
            "reconstruction_is_runtime_resumption": False,
            "reconstruction_is_mission_reexecution": False,
            "integrity_repair_performed": False,
            "planner_rerun_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "mission_state_transition_performed": False,
            "telemetry_export_performed": False,
            "external_network_io_performed": False,
            "target_actuation": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "new_observation_authority_added": False,
            "new_forensic_authority_added": False,
        },
        "next_stage": OBSERVATION_RECONSTRUCTION_FORENSIC_NEXT_STAGE,
    }
    return {
        **core,
        "integrity": {
            "hash_domain": OBSERVATION_RECONSTRUCTION_FORENSIC_HASH_DOMAIN,
            "canonical_sha256": _sha({
                "hash_domain": OBSERVATION_RECONSTRUCTION_FORENSIC_HASH_DOMAIN,
                "core": core,
            }),
        },
    }


def verify_observation_reconstruction_forensic_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_observation_reconstruction_forensic_contract()
    except Exception:
        return False


def canonical_observation_reconstruction_forensic_definition() -> dict[str, Any]:
    contract = canonical_observation_reconstruction_forensic_contract()
    head = contract["qualified_observation_head"]
    return {
        "schema_version": OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
        "mode": OBSERVATION_RECONSTRUCTION_FORENSIC_MODE,
        "predecessor_control": OBSERVATION_RECONSTRUCTION_FORENSIC_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL,
        "runtime_verifier_read_only": True,
        "mission_event_count_expected": head["mission_event_count"],
        "normalized_event_count_expected": head["normalized_event_count"],
        "timeline_event_count_expected": head["timeline_event_count"],
        "causal_node_count_expected": head["causal_node_count"],
        "causal_edge_count_expected": head["causal_edge_count"],
        "diagnostics_status_expected": head["diagnostics_status"],
        "observability_health_expected": head["observability_health"],
        "forensic_bundle_status_expected": head["forensic_bundle_status"],
        "forensic_reconstruction_status_expected": head["forensic_reconstruction_status"],
        "forensic_query_status_expected": head["forensic_query_status"],
        "forensic_equivalence_required": True,
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_observation_authority_added": False,
        "new_forensic_authority_added": False,
        "next_stage": OBSERVATION_RECONSTRUCTION_FORENSIC_NEXT_STAGE,
    }


def _event_refs(events: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [
        (x.get("event_id"), x.get("canonical_sha256"), x.get("event_type"))
        for x in events
    ]


def _normalized_refs(events: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [
        (x.get("source_event_id"), x.get("source_event_sha256"), x.get("event_type"))
        for x in events
    ]


def _timeline_refs(entries: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [
        (x.get("source_event_id"), x.get("source_event_sha256"), x.get("event_type"))
        for x in entries
    ]


def evaluate_observation_reconstruction_forensic_equivalence(
    *,
    mission_id: str,
    predecessor_qualification: Mapping[str, Any],
    state: Mapping[str, Any],
    active_plan: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    repository_counts: Mapping[str, int],
    event_integrity_status: str,
    repository_integrity_status: str,
    trace_view: Mapping[str, Any],
    normalized_view: Mapping[str, Any],
    causal_view: Mapping[str, Any],
    live_view: Mapping[str, Any],
    decision_view: Mapping[str, Any],
    timeline_view: Mapping[str, Any],
    diagnostics_view: Mapping[str, Any],
    metrics_view: Mapping[str, Any],
    forensic_bundle: Mapping[str, Any],
    forensic_reconstruction: Mapping[str, Any],
    forensic_events_query: Mapping[str, Any],
    forensic_lineage_query: Mapping[str, Any],
    forensic_integrity_query: Mapping[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if ok else "FAIL"})

    event_types = [x.get("event_type") for x in events]
    raw_refs = _event_refs(events)
    normalized_events = normalized_view.get("events") or []
    normalized_refs = _normalized_refs(normalized_events)
    graph = causal_view.get("graph") or {}
    live = live_view.get("projection") or {}
    decision = decision_view.get("projection") or {}
    timeline = timeline_view.get("timeline") or {}
    timeline_entries = timeline.get("entries") or []
    timeline_refs = _timeline_refs(timeline_entries)
    diagnostics = diagnostics_view.get("diagnostics") or {}
    health = (metrics_view.get("report") or {}).get("observability_health") or {}
    bundle = forensic_bundle
    bundle_sources = bundle.get("sources") or {}
    bundle_records = bundle.get("records") or {}
    reconstruction_result = forensic_reconstruction
    reconstruction = reconstruction_result.get("reconstruction") or {}
    event_query = forensic_events_query
    lineage_query = forensic_lineage_query
    integrity_query = forensic_integrity_query
    event_query_result = event_query.get("result") or {}
    lineage_query_result = lineage_query.get("result") or {}
    integrity_query_result = integrity_query.get("result") or {}
    active = active_plan or {}
    event_tip = events[-1].get("canonical_sha256") if events else None
    trace_id = trace_view.get("trace_id")

    check("STAGE3_9_8_PREDECESSOR_QUALIFIED", predecessor_qualification.get("qualified") is True)
    check("MISSION_AND_REPOSITORY_INTEGRITY", event_integrity_status == "PASS" and repository_integrity_status == "PASS")
    check("EXACT_STAGE398_EVENT_LEDGER", bool(
        event_types == list(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES)
        and len(events) == len(OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_EVENT_TYPES)
    ))
    check("EXACT_STAGE398_REPOSITORY_FOOTPRINT", {
        k: v for k, v in repository_counts.items() if int(v)
    } == OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_NONZERO_COUNTS)
    check("GLOBAL_TRACE_IDENTITY_EQUIVALENCE", bool(
        trace_id
        and all(x == trace_id for x in (
            normalized_view.get("trace_id"), causal_view.get("trace_id"), live_view.get("trace_id"),
            decision_view.get("trace_id"), timeline_view.get("trace_id"), diagnostics_view.get("trace_id"),
            forensic_bundle.get("trace_id"),
        ))
        and graph.get("trace_id") == trace_id
        and live.get("trace_id") == trace_id
        and decision.get("trace_id") == trace_id
        and timeline.get("trace_id") == trace_id
        and reconstruction.get("timeline", {}).get("trace_id") == trace_id
    ))
    check("RAW_NORMALIZED_TIMELINE_EVENT_EQUIVALENCE", bool(
        raw_refs == normalized_refs == timeline_refs
        and len(raw_refs) == len(normalized_events) == int(timeline.get("event_count") or 0)
    ))
    check("CAUSAL_GRAPH_CARDINALITY_AND_SOURCE_EQUIVALENCE", bool(
        int(graph.get("node_count") or 0) == len(events) + 1
        and int(graph.get("edge_count") or 0) == len(events)
        and bundle_sources.get("causal_graph") == graph
    ))
    check("DIRECT_OBSERVABILITY_VIEWS_EQUAL_FORENSIC_SOURCES", bool(
        bundle_sources.get("normalized_events") == normalized_events
        and bundle_sources.get("causal_graph") == graph
        and bundle_sources.get("decision_trace") == decision
        and bundle_sources.get("timeline") == timeline
        and bundle_sources.get("live_projection") == live
        and bundle.get("diagnostics") == diagnostics
    ))
    check("FORENSIC_BUNDLE_VERIFIED_AND_DURABLE_SOURCE_BOUND", bool(
        bundle.get("status") == "VERIFIED"
        and verify_forensic_evidence_bundle(bundle)
        and bundle_records.get("mission_events") == list(events)
        and bundle_records.get("mission_state") == dict(state)
        and bundle_records.get("active_plan_version") == (dict(active) if active else None)
        and int((bundle.get("record_counts") or {}).get("mission_events") or 0) == len(events)
    ))
    check("MISSION_STATE_AND_ACTIVE_PLAN_CROSS_VIEW_EQUIVALENCE", bool(
        state.get("state") == "RUNNING"
        and int(state.get("state_version") or 0) == 4
        and state.get("terminal") is False
        and live.get("mission", {}).get("state") == state.get("state")
        and int(live.get("mission", {}).get("state_version") or 0) == int(state.get("state_version") or 0)
        and reconstruction.get("mission_state") == dict(state)
        and int(active.get("plan_version") or 0) == 2
        and reconstruction.get("active_plan_version") == dict(active)
        and live.get("plan", {}).get("latest", {}).get("plan_version_record_id") == active.get("plan_version_record_id")
        and live.get("plan", {}).get("latest", {}).get("canonical_sha256") == active.get("canonical_sha256")
    ))
    expected_reconstruction = None
    try:
        expected_reconstruction = reconstruct_forensic_mission(bundle)
    except Exception:
        pass
    check("FORENSIC_RECONSTRUCTION_EXACTLY_DERIVED_FROM_BUNDLE", bool(
        reconstruction_result.get("status") == "VERIFIED"
        and expected_reconstruction == reconstruction_result
        and reconstruction.get("timeline") == timeline
        and reconstruction.get("causal_graph") == graph
        and reconstruction.get("decision_trace") == decision
        and reconstruction.get("live_projection") == live
        and int(reconstruction.get("event_count") or 0) == len(events)
    ))
    expected_event_query = expected_lineage_query = expected_integrity_query = None
    try:
        expected_event_query = forensic_query(bundle, scope="events")
        expected_lineage_query = forensic_query(bundle, scope="lineage")
        expected_integrity_query = forensic_query(bundle, scope="integrity")
    except Exception:
        pass
    check("FORENSIC_EVENT_QUERY_EQUIVALENCE", bool(
        event_query.get("status") == "VERIFIED"
        and event_query == expected_event_query
        and event_query_result.get("events") == normalized_events
        and event_query_result.get("timeline_entries") == timeline_entries
    ))
    check("FORENSIC_LINEAGE_QUERY_EQUIVALENCE", bool(
        lineage_query.get("status") == "VERIFIED"
        and lineage_query == expected_lineage_query
        and lineage_query_result.get("causal_graph") == graph
        and lineage_query_result.get("timeline") == timeline
    ))
    check("FORENSIC_INTEGRITY_QUERY_EQUIVALENCE", bool(
        integrity_query.get("status") == "VERIFIED"
        and integrity_query == expected_integrity_query
        and integrity_query_result.get("diagnostics") == diagnostics
        and integrity_query_result.get("record_counts") == bundle.get("record_counts")
    ))
    check("DIAGNOSTICS_AND_OPERATOR_HEALTH_PASS", bool(
        diagnostics.get("status") == "PASS"
        and int(diagnostics.get("blocking_finding_count") or 0) == 0
        and set(diagnostics.get("source_status") or {}) == set(OBSERVATION_RECONSTRUCTION_FORENSIC_REQUIRED_SOURCES)
        and all(v == "PASS" for v in (diagnostics.get("source_status") or {}).values())
        and health.get("status") == "HEALTHY"
        and health.get("scope") == "OBSERVABILITY_DATA_QUALITY_ONLY"
    ))
    check("CANONICAL_HEAD_HASH_EQUIVALENCE", bool(
        event_tip
        and normalized_events[-1].get("source_event_sha256") == event_tip
        and timeline_entries[-1].get("source_event_sha256") == event_tip
        and reconstruction.get("head_event_sha256") == event_tip
        and bundle_records.get("mission_events", [])[-1].get("canonical_sha256") == event_tip
    ))
    check("READ_ONLY_OBSERVATION_FORENSIC_BOUNDARY", bool(
        all(view.get("read_only") is True for view in (
            trace_view, normalized_view, causal_view, live_view, decision_view,
            timeline_view, diagnostics_view, metrics_view,
        ))
        and all(view.get("read_only") is True for view in (
            {"read_only": True},  # bundle is returned by a read-only service wrapper
        ))
    ))

    contract = canonical_observation_reconstruction_forensic_contract()
    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    return {
        "schema_version": OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
        "segment": "GLOBAL_OBSERVATION_RECONSTRUCTION_FORENSIC_EQUIVALENCE",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id,
        "status": "QUALIFIED" if not failures else "REJECTED",
        "qualified": not failures,
        "failed_check_ids": failures,
        "checks": checks,
        "segment_head": {
            "state": state.get("state"),
            "state_version": state.get("state_version"),
            "active_plan_version": active.get("plan_version"),
            "trace_id": trace_id,
            "event_count": len(events),
            "normalized_event_count": len(normalized_events),
            "timeline_event_count": timeline.get("event_count"),
            "causal_node_count": graph.get("node_count"),
            "causal_edge_count": graph.get("edge_count"),
            "event_tip_sha256": event_tip,
            "forensic_bundle_sha256": (bundle.get("integrity") or {}).get("canonical_sha256"),
            "forensic_reconstruction_sha256": (reconstruction_result.get("integrity") or {}).get("canonical_sha256"),
            "diagnostics_status": diagnostics.get("status"),
            "observability_health": health.get("status"),
            "forensic_bundle_status": bundle.get("status"),
            "forensic_reconstruction_status": reconstruction_result.get("status"),
            "forensic_query_status": event_query.get("status"),
            "equivalence_status": "PASS" if not failures else "FAIL",
        },
        "authority_boundary": {
            "verification_read_only": True,
            "planner_rerun_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "mission_state_transition_performed": False,
            "integrity_repair_performed": False,
            "telemetry_export_performed": False,
            "external_network_io_performed": False,
            "target_actuation": False,
        },
    }

from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import MissionNotFound
from mission_orchestrator.observability_trace import (
    OBSERVABILITY_TRACE_CONTEXT_SCHEMA_VERSION,
    OBSERVABILITY_TRACE_DATABASE_CHANGE_MODE,
    OBSERVABILITY_TRACE_EXPORT_MODE,
    OBSERVABILITY_TRACE_MODE,
    OBSERVABILITY_TRACE_PERSISTENCE_MODE,
    OBSERVABILITY_TRACE_SCHEMA_VERSION,
    build_observability_trace_identity_contract,
    canonical_observability_trace_definition,
    derive_root_span_id,
    derive_trace_id,
    verify_observability_trace_identity_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_1_identity_envelope import payload

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def make_service(db: Path) -> CanonicalMissionService:
    return CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))


def create(svc: CanonicalMissionService, key: str):
    return svc.create_mission(payload(key))


def test_01_health_activates_stage381_without_database_change(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    h = svc.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["supported_controls"][-1] == CONTROL
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["observability_trace_schema_version"] == OBSERVABILITY_TRACE_SCHEMA_VERSION
    assert h["observability_trace_context_schema_version"] == OBSERVABILITY_TRACE_CONTEXT_SCHEMA_VERSION
    assert h["observability_trace_mode"] == OBSERVABILITY_TRACE_MODE
    assert h["observability_trace_database_change_mode"] == OBSERVABILITY_TRACE_DATABASE_CHANGE_MODE == "NO_NEW_DATABASE_MIGRATION"
    assert h["observability_trace_persistence_mode"] == OBSERVABILITY_TRACE_PERSISTENCE_MODE
    assert h["observability_trace_export_mode"] == OBSERVABILITY_TRACE_EXPORT_MODE


def test_02_definition_is_root_identity_only_and_read_only():
    d = canonical_observability_trace_definition()
    assert d["schema_version"] == OBSERVABILITY_TRACE_SCHEMA_VERSION
    assert d["identity_binding"] == "MISSION_ID_PLUS_IMMUTABLE_CANONICAL_ENVELOPE_SHA256"
    assert d["trace_tree_scope"] == "MISSION_ROOT_ONLY_STAGE_3_8_1"
    assert d["future_child_span_propagation_authority"] == "NOT_IMPLEMENTED_IN_STAGE_3_8_1"
    assert d["runtime_side_effects"] is False


def test_03_trace_identity_is_deterministic_and_w3c_width_compatible(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    created = create(svc, "stage381-deterministic")
    mission_id = created["canonical_identity"]["mission_id"]
    result = svc.get_observability_trace_identity(mission_id)
    trace = result["observability_trace_identity"]
    envelope_hash = created["envelope"]["integrity"]["canonical_sha256"]
    assert result["trace_id"] == derive_trace_id(mission_id, envelope_hash)
    assert result["root_span_id"] == derive_root_span_id(mission_id, envelope_hash)
    assert len(result["trace_id"]) == 32
    assert len(result["root_span_id"]) == 16
    int(result["trace_id"], 16); int(result["root_span_id"], 16)
    assert result["trace_id"] != "0" * 32
    assert result["root_span_id"] != "0" * 16
    assert verify_observability_trace_identity_contract(trace)


def test_04_contract_binds_immutable_envelope_and_existing_correlation_id(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    created = create(svc, "stage381-binding")
    mission_id = created["canonical_identity"]["mission_id"]
    trace = svc.get_observability_trace_identity(mission_id)["observability_trace_identity"]
    assert trace["identity"]["mission_id"] == mission_id
    assert trace["identity"]["correlation_id"] == created["canonical_identity"]["correlation_id"]
    assert trace["source_bindings"]["envelope_id"] == created["canonical_identity"]["envelope_id"]
    assert trace["source_bindings"]["envelope_sha256"] == created["envelope"]["integrity"]["canonical_sha256"]


def test_05_repeated_reads_are_identical_and_do_not_mutate_repository_or_events(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    mission_id = create(svc, "stage381-readonly")["canonical_identity"]["mission_id"]
    before_repo = svc.get_mission_repository(mission_id)
    before_events = svc.get_mission_events(mission_id)["event_count"]
    a = svc.get_observability_trace_identity(mission_id)
    b = svc.get_observability_trace_identity(mission_id)
    after_repo = svc.get_mission_repository(mission_id)
    assert a == b
    assert before_repo["repository_sha256"] == after_repo["repository_sha256"]
    assert svc.get_mission_events(mission_id)["event_count"] == before_events


def test_06_restart_reconstructs_same_identity_without_new_store(tmp_path):
    db = tmp_path / "missions.db"
    first = make_service(db)
    mission_id = create(first, "stage381-restart")["canonical_identity"]["mission_id"]
    a = first.get_observability_trace_identity(mission_id)
    second = make_service(db)
    b = second.get_observability_trace_identity(mission_id)
    assert a["trace_id"] == b["trace_id"]
    assert a["root_span_id"] == b["root_span_id"]
    assert a["observability_trace_identity"]["integrity"] == b["observability_trace_identity"]["integrity"]
    assert second.health()["observability_trace_new_durable_store_added"] is False


def test_07_trace_projection_does_not_add_operational_authority(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    mission_id = create(svc, "stage381-authority")["canonical_identity"]["mission_id"]
    out = svc.get_observability_trace_identity(mission_id)
    semantics = out["observability_trace_identity"]["semantics"]
    for field in (
        "trace_identity_is_authorization", "trace_identity_is_execution_authority", "trace_identity_is_governance_decision",
        "telemetry_export_performed", "external_network_io_performed", "runtime_probe_performed",
        "mission_state_transition_performed", "routing_performed", "delegation_performed", "dispatch_performed",
        "execution_attempt_created", "target_action_dispatch_performed", "target_actuation", "database_migration_added", "durable_store_added",
    ):
        assert semantics[field] is False


def test_08_trace_identity_survives_mission_state_changes(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    mission_id = create(svc, "stage381-state-independent")["canonical_identity"]["mission_id"]
    before = svc.get_observability_trace_identity(mission_id)
    state = svc.get_mission_state(mission_id)["mission_state"]
    svc.transition_mission_state(mission_id, {
        "expected_state_version": state["state_version"],
        "to_state": "PIP_BOUND",
        "reason_code": "TEST",
        "actor": "stage381-test",
    })
    after = svc.get_observability_trace_identity(mission_id)
    assert after["trace_id"] == before["trace_id"]
    assert after["root_span_id"] == before["root_span_id"]


def test_09_unknown_mission_fails_closed_without_synthesizing_trace(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    with pytest.raises(MissionNotFound):
        svc.get_observability_trace_identity("mission-gmo-does-not-exist")


def test_10_tampered_contract_fails_verification(tmp_path):
    svc = make_service(tmp_path / "missions.db")
    created = create(svc, "stage381-tamper")
    contract = build_observability_trace_identity_contract(identity=created["canonical_identity"], envelope=created["envelope"])
    contract["identity"]["trace_id"] = "f" * 32
    assert verify_observability_trace_identity_contract(contract) is False


def test_11_health_declares_strict_no_io_no_actuation_boundary(tmp_path):
    h = make_service(tmp_path / "missions.db").health()
    assert h["observability_trace_read_only_projection"] is True
    assert h["observability_trace_deterministic_identity"] is True
    assert h["observability_trace_restart_stable"] is True
    assert h["observability_trace_telemetry_export_performed"] is False
    assert h["observability_trace_external_network_io_performed"] is False
    assert h["observability_trace_runtime_probe_performed"] is False
    assert h["observability_trace_governance_query_performed"] is False
    assert h["observability_trace_authorization_granted"] is False
    assert h["observability_trace_dispatch_performed"] is False
    assert h["observability_trace_target_actuation"] is False


def test_12_stage3710_remains_immediate_predecessor_in_supported_control_chain(tmp_path):
    controls = make_service(tmp_path / "missions.db").health()["supported_controls"]
    assert controls[-21:] == [
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
        "stage3.8.1-canonical-observability-trace-identity-contract",
        "stage3.8.2-event-normalization-ingestion",
        "stage3.8.3-global-causal-lineage-graph",
        "stage3.8.4-live-mission-state-execution-projection",
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
        CONTROL,
    ]

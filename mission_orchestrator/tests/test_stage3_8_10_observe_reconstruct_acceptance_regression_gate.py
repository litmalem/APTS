from copy import deepcopy

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.observe_reconstruct_acceptance_gate import (
    OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    REQUIRED_OBSERVE_RECONSTRUCT_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_8_CONTROLS,
    observe_reconstruct_acceptance_gate_contract,
)
from mission_orchestrator.observability_forensics import (
    forensic_query, reconstruct_forensic_mission, verify_forensic_evidence_bundle,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_1_identity_envelope import payload

STAGE3810_CONTROL = "stage3.8.10-observe-reconstruct-acceptance-regression-gate"
CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def _service(tmp_path, key="stage3810"):
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "stage3810.db"))
    service = CanonicalMissionService(repo)
    created = service.create_mission(payload(key))
    return repo, service, created["canonical_identity"]["mission_id"]


def test_static_closure_contract_is_declaration_only_and_preserves_boundary():
    gate = observe_reconstruct_acceptance_gate_contract()
    assert gate["baseline"] == "STAGE_3_8_1_THROUGH_3_8_9"
    assert gate["expected_repository_migration_level"] == 53
    assert tuple(gate["required_prior_controls"]) == REQUIRED_STAGE3_8_CONTROLS
    assert tuple(gate["required_gates"]) == REQUIRED_OBSERVE_RECONSTRUCT_ACCEPTANCE_GATES
    assert gate["declared_only"] is True
    assert gate["runtime_self_certification"] is False
    assert gate["external_acceptance_execution_required"] is True
    for key, value in gate.items():
        if key.startswith("new_") or key.startswith("closure_gate_is_"):
            assert value is False
    assert gate["stage389_verified_bundle_is_external_attestation"] is False
    assert gate["stage389_reconstruction_is_runtime_resumption"] is False
    assert gate["stage389_reconstruction_is_mission_reexecution"] is False


def test_health_activates_closure_without_migration_or_new_authority(tmp_path):
    _, service, _ = _service(tmp_path)
    health = service.health()
    assert health["control_version"] == CURRENT_CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["mission_repository_migration_level"] == OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL
    assert health["supported_controls"][-12:] == [
        "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api",
        STAGE3810_CONTROL,
        "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract",
        "stage3.9.2-intake-lifecycle-e2e-segment-qualification",
        "stage3.9.3-planning-task-graph-dependency-verification",
        "stage3.9.4-routing-delegation-governance-continuity",
        "stage3.9.5-dispatch-execution-evidence-continuity",
        "stage3.9.6-task-completion-mission-outcome-closure",
        "stage3.9.7-adaptation-replanning-e2e-scenario",
        "stage3.9.8-restart-replay-recovery-e2e-verification",
        "stage3.9.9-global-observation-reconstruction-forensic-equivalence",
        CURRENT_CONTROL,
    ]
    assert health["stage3_8_observe_reconstruct_acceptance_gate_declared_only"] is True
    assert health["stage3_8_observe_reconstruct_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_8_observe_reconstruct_acceptance_gate_new_database_migration_added"] is False
    assert health["stage3_8_observe_reconstruct_acceptance_gate_new_durable_store_added"] is False
    assert health["stage3_8_observe_reconstruct_acceptance_gate_new_repair_authority_added"] is False
    assert health["stage3_8_observe_reconstruct_acceptance_gate_new_target_actuation_added"] is False


def test_observe_reconstruct_cross_view_consistency_and_restart_stability(tmp_path):
    path = tmp_path / "stage3810.db"
    repo = MissionRepository(driver="sqlite", sqlite_path=str(path))
    service = CanonicalMissionService(repo)
    mission_id = service.create_mission(payload("stage3810-cross-view"))["canonical_identity"]["mission_id"]
    bundle_response = service.get_forensic_evidence_bundle(mission_id)
    bundle = bundle_response["bundle"]
    reconstruction = service.get_forensic_reconstruction(mission_id)["result"]
    events = service.query_forensic_mission(mission_id, scope="events")["result"]
    assert verify_forensic_evidence_bundle(bundle)
    assert bundle["status"] == reconstruction["status"] == events["status"] == "VERIFIED"
    assert reconstruction == reconstruct_forensic_mission(bundle)
    assert events == forensic_query(bundle, scope="events")
    assert len(events["result"]["events"]) == bundle["record_counts"]["mission_events"]
    assert reconstruction["reconstruction"]["event_count"] == bundle["record_counts"]["mission_events"]
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(path)))
    assert restarted.get_forensic_evidence_bundle(mission_id)["bundle"] == bundle
    assert restarted.get_forensic_reconstruction(mission_id)["result"] == reconstruction


def test_closure_preserves_stage389_fail_closed_tamper_semantics(tmp_path):
    _, service, mission_id = _service(tmp_path, "stage3810-tamper")
    bundle = service.get_forensic_evidence_bundle(mission_id)["bundle"]
    tampered = deepcopy(bundle)
    tampered["sources"]["timeline"]["event_count"] += 1
    assert verify_forensic_evidence_bundle(tampered) is False
    try:
        reconstruct_forensic_mission(tampered)
    except ValueError as exc:
        assert "unverified forensic evidence bundle" in str(exc)
    else:
        raise AssertionError("tampered forensic bundle must fail closed")

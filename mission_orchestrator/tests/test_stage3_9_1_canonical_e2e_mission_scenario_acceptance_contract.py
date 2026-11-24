from __future__ import annotations

import json
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.canonical import normalize_create_request
from mission_orchestrator.e2e_mission_acceptance import (
    E2E_ACCEPTANCE_INVARIANTS,
    E2E_ACCEPTANCE_PHASES,
    E2E_FAILURE_CRITERIA,
    E2E_MISSION_ACCEPTANCE_BASELINE,
    E2E_MISSION_ACCEPTANCE_DATABASE_CHANGE_MODE,
    E2E_MISSION_ACCEPTANCE_ENVIRONMENT_MODE,
    E2E_MISSION_ACCEPTANCE_EXPECTED_MIGRATION_LEVEL,
    E2E_MISSION_ACCEPTANCE_MODE,
    E2E_MISSION_ACCEPTANCE_PERSISTENCE_MODE,
    E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION,
    E2E_MISSION_SCENARIO_ID,
    E2E_MISSION_SCENARIO_SCHEMA_VERSION,
    E2E_REQUIRED_IDENTITY_FAMILIES,
    E2E_STAGE391_FORBIDDEN_SIDE_EFFECTS,
    E2E_SUCCESS_CRITERIA,
    REQUIRED_STAGE_CLOSURE_CONTROLS,
    canonical_e2e_mission_acceptance_contract,
    canonical_e2e_mission_acceptance_definition,
    materialize_canonical_e2e_mission_request,
    verify_canonical_e2e_mission_acceptance_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_1_identity_envelope import payload

CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE391_CONTROL = "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract"
STAGE392_CONTROL = "stage3.9.2-intake-lifecycle-e2e-segment-qualification"
PREDECESSOR_CONTROL = "stage3.8.10-observe-reconstruct-acceptance-regression-gate"


def make_service(db: Path) -> CanonicalMissionService:
    return CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))


def test_01_contract_is_canonical_hashed_and_stage391_declaration_only():
    contract = canonical_e2e_mission_acceptance_contract()
    assert verify_canonical_e2e_mission_acceptance_contract(contract)
    assert contract["schema_version"] == E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION
    assert contract["mode"] == E2E_MISSION_ACCEPTANCE_MODE
    assert contract["baseline"] == E2E_MISSION_ACCEPTANCE_BASELINE
    assert contract["expected_repository_migration_level"] == 53
    assert contract["scenario"]["schema_version"] == E2E_MISSION_SCENARIO_SCHEMA_VERSION
    assert contract["scenario"]["scenario_id"] == E2E_MISSION_SCENARIO_ID
    boundary = contract["stage391_boundary"]
    assert boundary["declared_only"] is True
    assert boundary["runtime_self_certification"] is False
    assert boundary["external_acceptance_execution_required"] is True
    assert boundary["runtime_side_effects"] is False
    for key, value in boundary.items():
        if key.startswith("new_"):
            assert value is False


def test_02_acceptance_phase_map_is_frozen_from_391_through_3910():
    contract = canonical_e2e_mission_acceptance_contract()
    observed = [(item["stage"], item["phase"]) for item in contract["acceptance_phases"]]
    assert observed == list(E2E_ACCEPTANCE_PHASES)
    assert [stage for stage, _ in observed] == [
        "3.9.1", "3.9.2", "3.9.3", "3.9.4", "3.9.5",
        "3.9.6", "3.9.7", "3.9.8", "3.9.9", "3.9.10",
    ]
    assert observed[0][1] == "CANONICAL_E2E_MISSION_SCENARIO_AND_ACCEPTANCE_CONTRACT"
    assert observed[-1][1] == "GLOBAL_ACCEPTANCE_AND_REGRESSION_GATE"


def test_03_all_prior_stage_closure_controls_are_explicit_prerequisites():
    contract = canonical_e2e_mission_acceptance_contract()
    assert tuple(contract["required_stage_closure_controls"]) == REQUIRED_STAGE_CLOSURE_CONTROLS
    assert REQUIRED_STAGE_CLOSURE_CONTROLS == (
        "stage3.1.10-acceptance-regression-gate",
        "stage3.2.10-lifecycle-acceptance-regression-gate",
        "stage3.3.10-planning-acceptance-regression-gate",
        "stage3.4.10-routing-delegation-acceptance-regression-gate",
        "stage3.5.10-execution-dispatch-acceptance-regression-gate",
        "stage3.6.10-outcome-acceptance-regression-gate",
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
        PREDECESSOR_CONTROL,
    )


def test_04_identity_family_contract_covers_cross_stage_lineage_without_aliases():
    contract = canonical_e2e_mission_acceptance_contract()
    identities = contract["required_identity_families"]
    assert identities == [
        {"name": name, "prefix": prefix} for name, prefix in E2E_REQUIRED_IDENTITY_FAMILIES
    ]
    names = [item["name"] for item in identities]
    prefixes = [item["prefix"] for item in identities]
    assert len(names) == len(set(names))
    assert len(prefixes) == len(set(prefixes))
    for required in (
        "mission_id", "plan_id", "planned_task_id", "route_decision_id", "delegation_id",
        "execution_attempt_id", "execution_result_id", "task_outcome_id",
        "mission_outcome_aggregation_id", "adaptation_episode_id", "replan_commit_id",
    ):
        assert required in names


def test_05_scenario_fixture_is_control_plane_sandbox_and_uses_supported_success_metrics():
    contract = canonical_e2e_mission_acceptance_contract()
    scenario = contract["scenario"]
    request = scenario["mission_request"]
    assert scenario["environment_mode"] == E2E_MISSION_ACCEPTANCE_ENVIRONMENT_MODE
    assert request["mission_kind"] == "E2E_ORCHESTRATOR_ACCEPTANCE"
    assert request["required_subsystems"] == ["CTI"]
    assert request["budgets"]["risk_ceiling"] == "LOW"
    assert request["metadata"]["external_target_actuation_allowed"] is False
    assert request["success_criteria"] == [
        {"metric": "all_tasks_verified_complete", "expected": True},
        {"metric": "terminal_non_success_present", "expected": False},
    ]
    assert scenario["trace_expectation"]["forensic_equivalence_required"] is True


def test_06_run_materialization_changes_only_declared_nonsemantic_fields_and_normalizes():
    first = materialize_canonical_e2e_mission_request("run-A")
    replay = materialize_canonical_e2e_mission_request("run-A")
    second = materialize_canonical_e2e_mission_request("run-B")
    assert first == replay
    assert first["idempotency_key"] == "stage391-e2e-run-A"
    assert second["idempotency_key"] == "stage391-e2e-run-B"
    assert first["metadata"]["run_id"] == "run-A"
    assert second["metadata"]["run_id"] == "run-B"
    first_semantic = deepcopy(first)
    second_semantic = deepcopy(second)
    first_semantic.pop("idempotency_key")
    second_semantic.pop("idempotency_key")
    first_semantic["metadata"].pop("run_id")
    second_semantic["metadata"].pop("run_id")
    assert first_semantic == second_semantic
    normalized = normalize_create_request(first)
    assert normalized["required_subsystems"] == ["CTI"]
    assert normalized["mission_kind"] == "E2E_ORCHESTRATOR_ACCEPTANCE"


def test_07_run_id_validation_is_fail_closed():
    for invalid in ("", " bad", "bad/run", "bad:run", "x" * 65, None, 42):
        with pytest.raises(ValueError):
            materialize_canonical_e2e_mission_request(invalid)  # type: ignore[arg-type]


def test_08_contract_tampering_breaks_integrity_verification():
    contract = canonical_e2e_mission_acceptance_contract()
    tampered = deepcopy(contract)
    tampered["scenario"]["mission_request"]["budgets"]["risk_ceiling"] = "HIGH"
    assert verify_canonical_e2e_mission_acceptance_contract(tampered) is False
    tampered = deepcopy(contract)
    tampered["stage391_boundary"]["new_execution_authority_added"] = True
    assert verify_canonical_e2e_mission_acceptance_contract(tampered) is False


def test_09_health_activates_stage391_without_migration_or_durable_store(tmp_path):
    service = make_service(tmp_path / "stage391.db")
    health = service.health()
    assert health["control_version"] == CURRENT_CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][-10:] == [STAGE391_CONTROL, STAGE392_CONTROL, "stage3.9.3-planning-task-graph-dependency-verification", "stage3.9.4-routing-delegation-governance-continuity", "stage3.9.5-dispatch-execution-evidence-continuity", "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CURRENT_CONTROL]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["stage3_9_e2e_mission_acceptance_schema_version"] == E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION
    assert health["stage3_9_e2e_mission_scenario_schema_version"] == E2E_MISSION_SCENARIO_SCHEMA_VERSION
    assert health["stage3_9_e2e_mission_acceptance_expected_migration_level"] == 53
    assert health["stage3_9_e2e_mission_acceptance_database_change_mode"] == E2E_MISSION_ACCEPTANCE_DATABASE_CHANGE_MODE
    assert health["stage3_9_e2e_mission_acceptance_persistence_mode"] == E2E_MISSION_ACCEPTANCE_PERSISTENCE_MODE
    assert health["stage3_9_e2e_mission_acceptance_new_database_migration_added"] is False
    assert health["stage3_9_e2e_mission_acceptance_new_durable_store_added"] is False


def test_10_health_exposes_acceptance_invariants_and_no_authority_expansion(tmp_path):
    health = make_service(tmp_path / "health391.db").health()
    assert health["stage3_9_e2e_mission_acceptance_required_stage_closure_controls"] == list(REQUIRED_STAGE_CLOSURE_CONTROLS)
    assert health["stage3_9_e2e_mission_acceptance_invariants"] == list(E2E_ACCEPTANCE_INVARIANTS)
    assert health["stage3_9_e2e_mission_acceptance_success_criteria"] == list(E2E_SUCCESS_CRITERIA)
    assert health["stage3_9_e2e_mission_acceptance_failure_criteria"] == list(E2E_FAILURE_CRITERIA)
    assert health["stage3_9_e2e_mission_acceptance_forbidden_side_effects"] == list(E2E_STAGE391_FORBIDDEN_SIDE_EFFECTS)
    assert health["stage3_9_e2e_mission_acceptance_declared_only"] is True
    assert health["stage3_9_e2e_mission_acceptance_runtime_side_effects"] is False
    for field in (
        "new_execution_authority_added", "new_governance_authority_added",
        "new_routing_authority_added", "new_delegation_authority_added",
        "new_dispatch_authority_added", "new_target_actuation_authority_added",
        "new_external_network_io_added", "new_telemetry_export_added",
        "new_database_migration_added", "new_durable_store_added",
    ):
        assert health[f"stage3_9_e2e_mission_acceptance_{field}"] is False


def test_11_service_definition_is_deterministic_restart_stable_and_source_equivalent(tmp_path):
    db = tmp_path / "restart391.db"
    first = make_service(db).get_e2e_mission_acceptance_contract_definition()
    second = make_service(db).get_e2e_mission_acceptance_contract_definition()
    assert first == second
    assert first["status"] == "completed"
    assert first["control_version"] == CURRENT_CONTROL
    assert first["definition"] == canonical_e2e_mission_acceptance_definition()
    assert first["contract"] == canonical_e2e_mission_acceptance_contract()
    assert first["definition"]["contract_sha256"] == first["contract"]["integrity"]["canonical_sha256"]
    assert first["definition"]["next_stage"] == "3.9.2"


def test_12_http_contract_route_is_read_only_and_does_not_change_mission_records(tmp_path):
    db = tmp_path / "http391.db"
    repo = MissionRepository(driver="sqlite", sqlite_path=str(db))
    service = CanonicalMissionService(repo)
    created = service.create_mission(payload("stage391-http-readonly"))
    mission_id = created["canonical_identity"]["mission_id"]
    before = repo.get_repository_record_counts(mission_id)

    handler = type("Stage391Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/mission-scenario-acceptance-contract") as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body == service.get_e2e_mission_acceptance_contract_definition()
        assert body["contract"]["scenario"]["scenario_id"] == E2E_MISSION_SCENARIO_ID
        assert verify_canonical_e2e_mission_acceptance_contract(body["contract"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    after = repo.get_repository_record_counts(mission_id)
    assert after == before

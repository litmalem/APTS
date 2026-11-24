from __future__ import annotations

import json
from copy import deepcopy
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_mission_acceptance import (
    E2E_MISSION_SCENARIO_ID,
    REQUIRED_STAGE_CLOSURE_CONTROLS,
    canonical_e2e_mission_acceptance_contract,
    verify_canonical_e2e_mission_acceptance_contract,
)
from mission_orchestrator.e2e_observation_reconstruction_forensic_equivalence import (
    OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
    canonical_observation_reconstruction_forensic_contract,
    verify_observation_reconstruction_forensic_contract,
)
from mission_orchestrator.global_mission_acceptance_gate import (
    GLOBAL_MISSION_ACCEPTANCE_GATE_BASELINE,
    GLOBAL_MISSION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    GLOBAL_MISSION_ACCEPTANCE_GATE_NEXT_STAGE,
    GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL,
    GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION,
    GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT,
    REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_9_CONTROLS,
    canonical_global_mission_acceptance_gate_contract,
    canonical_global_mission_acceptance_gate_definition,
    verify_global_mission_acceptance_gate_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_9_8_restart_replay_recovery_e2e_verification import provision as provision_stage398

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
SERVER_VERSION = "APTSMissionOrchestrator/3.9.10"


@pytest.fixture(scope="module")
def shared_context(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("stage3910-shared")
    service, restarted, governance, runtime, mission_id, rows, body, checkpoint, before = provision_stage398(
        tmp_path, "shared3910"
    )
    pre = {
        "events": restarted.get_mission_events(mission_id),
        "counts": restarted.repository.get_repository_record_counts(mission_id),
        "state": restarted.get_mission_state(mission_id),
        "calls": (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls),
    }
    stage399 = restarted.get_e2e_observation_reconstruction_forensic_equivalence(mission_id)
    gate = restarted.get_global_mission_acceptance_regression_gate_contract_definition()
    post = {
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
        "stage399": stage399,
        "gate": gate,
        "pre": pre,
        "post": post,
    }


def test_01_canonical_gate_contract_binds_stage399_and_stage391():
    gate = canonical_global_mission_acceptance_gate_contract()
    stage391 = canonical_e2e_mission_acceptance_contract()
    stage399 = canonical_observation_reconstruction_forensic_contract()
    assert verify_global_mission_acceptance_gate_contract(gate)
    assert gate["baseline"] == GLOBAL_MISSION_ACCEPTANCE_GATE_BASELINE
    assert gate["predecessor_control"] == GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL
    assert gate["predecessor_schema_version"] == OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION
    assert gate["predecessor_contract_sha256"] == stage399["integrity"]["canonical_sha256"]
    assert gate["canonical_e2e_contract_sha256"] == stage391["integrity"]["canonical_sha256"]
    assert gate["canonical_e2e_scenario_id"] == E2E_MISSION_SCENARIO_ID


def test_02_gate_contract_is_frozen_and_tamper_fails_closed():
    gate = canonical_global_mission_acceptance_gate_contract()
    forged = deepcopy(gate)
    forged["closure_semantics"]["runtime_self_certification"] = True
    assert verify_global_mission_acceptance_gate_contract(forged) is False
    forged = deepcopy(gate)
    forged["next_stage"] = "3.9.11"
    assert verify_global_mission_acceptance_gate_contract(forged) is False


def test_03_health_activates_stage3910_without_migration(shared_context):
    health = shared_context["restarted"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == SERVER_VERSION
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == GLOBAL_MISSION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 53
    assert health["supported_controls"][-2:] == [GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL, CONTROL]
    assert health["stage3_9_10_global_mission_acceptance_gate_schema_version"] == GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION


def test_04_health_declares_all_stage39_prior_controls_and_global_gates(shared_context):
    health = shared_context["restarted"].health()
    assert tuple(health["stage3_9_10_required_stage3_9_controls"]) == REQUIRED_STAGE3_9_CONTROLS
    assert tuple(health["stage3_9_10_required_gates"]) == REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES
    assert len(REQUIRED_STAGE3_9_CONTROLS) == 9
    assert all(control in health["supported_controls"] for control in REQUIRED_STAGE3_9_CONTROLS)


def test_05_health_preserves_final_authority_and_persistence_boundary(shared_context):
    health = shared_context["restarted"].health()
    assert health["stage3_9_10_declared_only"] is True
    assert health["stage3_9_10_runtime_self_certification"] is False
    assert health["stage3_9_10_external_acceptance_execution_required"] is True
    assert health["stage3_9_10_full_historical_regression_required"] is True
    for key in (
        "stage3_9_10_new_database_migration_added",
        "stage3_9_10_new_durable_store_added",
        "stage3_9_10_new_execution_authority_added",
        "stage3_9_10_new_governance_authority_added",
        "stage3_9_10_new_routing_authority_added",
        "stage3_9_10_new_delegation_authority_added",
        "stage3_9_10_new_dispatch_authority_added",
        "stage3_9_10_new_recovery_authority_added",
        "stage3_9_10_new_observation_authority_added",
        "stage3_9_10_new_forensic_authority_added",
        "stage3_9_10_telemetry_export_performed",
        "stage3_9_10_external_network_io_performed",
        "stage3_9_10_target_actuation",
    ):
        assert health[key] is False, key


def test_06_gate_definition_is_sha_bound_and_points_to_stage4_1():
    definition = canonical_global_mission_acceptance_gate_definition()
    contract = canonical_global_mission_acceptance_gate_contract()
    assert definition["contract_sha256"] == contract["integrity"]["canonical_sha256"]
    assert definition["predecessor_contract_sha256"] == contract["predecessor_contract_sha256"]
    assert definition["required_stage_domain_closure_control_count"] == 8
    assert definition["required_stage3_9_control_count"] == 9
    assert definition["required_gate_count"] == len(REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES)
    assert definition["stage_output"] == GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT
    assert definition["next_stage"] == GLOBAL_MISSION_ACCEPTANCE_GATE_NEXT_STAGE == "4.1"


def test_07_contract_api_exposes_final_gate_read_only(shared_context):
    service = shared_context["restarted"]
    handler = type("Stage3910Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/e2e/global-mission-orchestrator-acceptance-regression-gate-contract") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["control_version"] == CONTROL
        assert payload["definition"]["schema_version"] == GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION
        assert payload["definition"]["stage_output"] == "GLOBAL_MISSION_ORCHESTRATOR"
        assert payload["definition"]["next_stage"] == "4.1"
        assert payload["read_only"] is True
        assert payload["runtime_self_certification"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_08_stage391_canonical_acceptance_contract_remains_frozen():
    contract = canonical_e2e_mission_acceptance_contract()
    assert verify_canonical_e2e_mission_acceptance_contract(contract)
    assert contract["scenario"]["scenario_id"] == E2E_MISSION_SCENARIO_ID
    assert contract["acceptance_phases"][-1] == {
        "stage": "3.9.10", "phase": "GLOBAL_ACCEPTANCE_AND_REGRESSION_GATE"
    }


def test_09_stage399_predecessor_contract_remains_canonical():
    contract = canonical_observation_reconstruction_forensic_contract()
    assert verify_observation_reconstruction_forensic_contract(contract)
    assert contract["next_stage"] == "3.9.10"
    assert contract["qualified_observation_head"]["equivalence_status"] == "PASS"


def test_10_stage399_predecessor_qualification_is_still_qualified(shared_context):
    proof = shared_context["stage399"]
    assert proof["qualification"]["status"] == "QUALIFIED"
    assert proof["qualification"]["qualified"] is True
    assert proof["qualification"]["segment_head"]["equivalence_status"] == "PASS"
    assert proof["qualification"]["segment_head"]["event_count"] == 50


def test_11_final_gate_and_stage399_verification_are_read_only(shared_context):
    assert shared_context["post"]["events"] == shared_context["pre"]["events"]
    assert shared_context["post"]["counts"] == shared_context["pre"]["counts"]
    assert shared_context["post"]["state"] == shared_context["pre"]["state"]
    assert shared_context["stage399"]["read_only"] is True
    assert shared_context["gate"]["read_only"] is True


def test_12_final_gate_performs_no_governance_or_runtime_io(shared_context):
    assert shared_context["post"]["calls"] == shared_context["pre"]["calls"]
    gate = shared_context["gate"]["contract"]
    boundary = gate["authority_boundary"]
    assert boundary["runtime_governance_query_performed"] is False
    assert boundary["runtime_runtime_query_performed"] is False
    assert boundary["runtime_dispatch_performed"] is False
    assert boundary["runtime_execution_attempt_created"] is False
    assert boundary["runtime_external_network_io_performed"] is False
    assert boundary["runtime_target_actuation"] is False


def test_13_all_stage3_domain_closure_controls_are_present(shared_context):
    health = shared_context["restarted"].health()
    assert tuple(canonical_global_mission_acceptance_gate_contract()["required_stage_domain_closure_controls"]) == REQUIRED_STAGE_CLOSURE_CONTROLS
    assert len(REQUIRED_STAGE_CLOSURE_CONTROLS) == 8
    assert all(control in health["supported_controls"] for control in REQUIRED_STAGE_CLOSURE_CONTROLS)


def test_14_pass_fail_authority_remains_external_acceptance_harness():
    contract = canonical_global_mission_acceptance_gate_contract()
    semantics = contract["closure_semantics"]
    assert semantics["declared_only"] is True
    assert semantics["runtime_self_certification"] is False
    assert semantics["external_acceptance_execution_required"] is True
    assert semantics["acceptance_harness_is_pass_fail_authority"] is True
    assert semantics["full_historical_regression_required"] is True
    assert "FULL_HISTORICAL_PYTEST_REGRESSION" in contract["required_gates"]


def test_15_stage3_closes_as_global_mission_orchestrator_and_hands_to_stage4(shared_context):
    health = shared_context["restarted"].health()
    gate = shared_context["gate"]["contract"]
    assert gate["stage_output"] == health["stage3_9_10_stage_output"] == "GLOBAL_MISSION_ORCHESTRATOR"
    assert gate["next_stage"] == health["stage3_9_10_next_stage"] == "4.1"
    assert gate["expected_repository_migration_level"] == 53

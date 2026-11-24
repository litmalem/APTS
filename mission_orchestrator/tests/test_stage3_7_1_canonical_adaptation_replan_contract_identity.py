from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import inspect
import json
import sqlite3

import pytest

from mission_orchestrator.adaptation_replan import (
    ADAPTATION_EPISODE_ID_PREFIX,
    ADAPTATION_EPISODE_INITIAL_STATE,
    ADAPTATION_EPISODE_STATES,
    ADAPTATION_REPLAN_ALLOWED_MISSION_STATES,
    ADAPTATION_REPLAN_AUTHORITY,
    ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION,
    ADAPTATION_REPLAN_MODE,
    ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION,
    REPLAN_CANDIDATE_ID_PREFIX,
    REPLAN_COMMIT_ID_PREFIX,
    REPLAN_DECISION_ID_PREFIX,
    REPLAN_SNAPSHOT_ID_PREFIX,
    REPLAN_TRIGGER_ID_PREFIX,
    REPLAN_TRIGGER_SOURCES,
    canonical_adaptation_replan_definition,
    verify_adaptation_replan_contract,
)
from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionAdaptationReplanConflict,
    MissionAdaptationReplanGuardRejected,
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_3_8_task_readiness_scheduling_projection import make_service, provision_active


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision_running(service, key: str):
    mission_id, active = provision_active(service, key)
    execute(service, mission_id, "START", f"run-{key}")
    return mission_id, active


def adaptation_request(service, mission_id: str, active: dict, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage371-adapt-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "trigger_source": "OPERATOR_REQUEST",
        "trigger_code": "OPERATOR_INTERVENTION",
        "evidence_refs": [f"operator-ticket:{key}"],
        "detected_by": "stage3.7.1-pytest",
        "reason": "Materialize canonical adaptation/replan detection identity",
        "metadata": {"stage": "3.7.1", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage371_contract_identity_and_migration_45(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == [
        "stage3.7.1-canonical-adaptation-replan-contract-identity",
        "stage3.7.2-adaptation-trigger-detection-classification",
        "stage3.7.3-replan-eligibility-governance-gate",
        "stage3.7.4-canonical-replan-snapshot-context-binding",
        "stage3.7.5-deterministic-replan-candidate-generation",
        "stage3.7.6-replan-candidate-validation-delta-feasibility-gate",
        "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization",
        "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["adaptation_replan_stage_schema_version"] == ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION
    assert health["adaptation_replan_contract_schema_version"] == ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION
    assert health["adaptation_replan_mode"] == ADAPTATION_REPLAN_MODE
    assert health["adaptation_replan_authority"] == ADAPTATION_REPLAN_AUTHORITY
    assert health["adaptation_episode_identity_prefix"] == ADAPTATION_EPISODE_ID_PREFIX
    assert health["replan_trigger_identity_prefix"] == REPLAN_TRIGGER_ID_PREFIX
    assert health["adaptation_replan_database_migration_level"] == 45
    assert health["adaptation_replan_persistence_store"] == "mission_adaptation_replan_contracts"
    assert health["adaptation_replan_terminal_reopening_allowed"] is False
    assert health["adaptation_replan_planner_invocation_performed"] is False
    assert health["adaptation_replan_dispatch_performed"] is False
    assert health["adaptation_replan_target_actuation"] is False


def test_definition_reserves_future_identity_namespaces_without_materializing_them(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_running(service, "definition")
    result = service.get_adaptation_replan_definition(mission_id)
    definition = result["adaptation_replan_definition"]
    assert definition == canonical_adaptation_replan_definition()
    assert definition["episode_initial_state"] == ADAPTATION_EPISODE_INITIAL_STATE
    assert definition["episode_state_model"] == list(ADAPTATION_EPISODE_STATES)
    assert definition["allowed_mission_states"] == sorted(ADAPTATION_REPLAN_ALLOWED_MISSION_STATES)
    assert definition["trigger_sources"] == list(REPLAN_TRIGGER_SOURCES)
    assert definition["reserved_future_identity_prefixes"] == {
        "replan_snapshot": REPLAN_SNAPSHOT_ID_PREFIX,
        "replan_candidate": REPLAN_CANDIDATE_ID_PREFIX,
        "replan_decision": REPLAN_DECISION_ID_PREFIX,
        "replan_commit": REPLAN_COMMIT_ID_PREFIX,
    }
    assert definition["next_stage"] == "3.7.2"


def test_materialization_creates_canonical_episode_and_trigger_identity_bound_to_plan_generation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "materialize")
    result = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "materialize")
    )
    assert result["idempotent_replay"] is False
    assert result["adaptation_episode_id"].startswith(ADAPTATION_EPISODE_ID_PREFIX)
    assert result["replan_trigger_id"].startswith(REPLAN_TRIGGER_ID_PREFIX)
    assert result["episode_state"] == "DETECTED"
    assert result["source_plan_version_record_id"] == active["plan_version_record_id"]
    assert result["source_plan_generation"] == active["plan_version"] == 1
    assert result["target_plan_generation"] == 2
    assert verify_adaptation_replan_contract(result["adaptation_replan_contract"])
    assert result["detection_event"]["event_type"] == "MISSION_ADAPTATION_REPLAN_DETECTED"
    assert result["detection_event"]["causation_id"] == result["adaptation_episode_id"]


def test_stage371_detection_does_not_transition_lifecycle_or_invoke_replan_planner(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "boundary")
    before_state = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    before_versions = service.get_plan_version_history(mission_id)
    result = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "boundary")
    )
    after_state = service.get_mission_state(mission_id)["mission_state"]
    after_versions = service.get_plan_version_history(mission_id)
    assert after_state == before_state
    assert len(after_versions["plan_versions"]) == len(before_versions["plan_versions"]) == 1
    assert service.get_active_plan_version(mission_id)["plan_version_record_id"] == active["plan_version_record_id"]
    assert result["lifecycle_replan_requested"] is False
    assert result["planner_invocation_performed"] is False
    assert result["plan_supersession_performed"] is False
    assert result["historical_plan_mutation_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False


@pytest.mark.parametrize("wait_command", ["WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"])
def test_detection_is_allowed_from_canonical_waiting_states(tmp_path, wait_command):
    service = make_service(tmp_path / f"{wait_command}.db")
    mission_id, active = provision_running(service, wait_command.lower())
    execute(service, mission_id, wait_command, f"wait-{wait_command}")
    state = service.get_mission_state(mission_id)["mission_state"]
    assert state["state"] in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES
    result = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, f"wait-{wait_command}")
    )
    assert result["source_bindings"]["source_state"] == state["state"]


def test_detection_rejects_replanning_state_to_avoid_duplicate_replan_episode_semantics(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "already-replanning")
    execute(service, mission_id, "REPLAN", "already-replanning")
    with pytest.raises(MissionAdaptationReplanGuardRejected, match="REPLANNING"):
        service.create_adaptation_replan(
            mission_id, adaptation_request(service, mission_id, active, "already-replanning")
        )


def test_detection_rejects_terminal_mission_and_never_reopens_it(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "terminal")
    execute(service, mission_id, "ABORT", "terminal-abort")
    terminal = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    with pytest.raises(MissionAdaptationReplanGuardRejected, match="terminal"):
        service.create_adaptation_replan(
            mission_id, adaptation_request(service, mission_id, active, "terminal")
        )
    assert service.get_mission_state(mission_id)["mission_state"] == terminal
    assert terminal["terminal"] is True


def test_detection_rejects_stale_mission_or_active_plan_binding(tmp_path):
    service = make_service(tmp_path / "stale-bindings.db")
    mission_id, active = provision_running(service, "stale-bindings")
    cases = [
        ("expected_version_sha256", "0" * 64, MissionConcurrencyConflict, "expected_version_sha256"),
        ("expected_state_version", 999999, MissionConcurrencyConflict, "expected_state_version"),
        ("expected_active_plan_version_record_id", "pver-wrong", MissionConcurrencyConflict, "active Plan head"),
        ("expected_active_plan_version", 99, MissionConcurrencyConflict, "active Plan head"),
        ("expected_active_plan_sha256", "0" * 64, MissionConcurrencyConflict, "active Plan head"),
    ]
    for index, (field, value, exc_type, message) in enumerate(cases):
        payload = adaptation_request(service, mission_id, active, f"stale-{index}")
        payload[field] = value
        with pytest.raises(exc_type, match=message):
            service.create_adaptation_replan(mission_id, payload)


def test_request_rejects_caller_supplied_future_or_side_effect_authority_surfaces(tmp_path):
    service = make_service(tmp_path / "forbidden-surfaces.db")
    mission_id, active = provision_running(service, "forbidden-surfaces")
    fields = [
        "classification", "eligibility", "snapshot", "lifecycle_command", "planner_output",
        "plan_delta", "candidate", "decision", "commit", "governance_authorization",
        "dispatch", "execution", "terminal_reopening", "actuation",
    ]
    for index, field in enumerate(fields):
        payload = adaptation_request(service, mission_id, active, f"surface-{index}")
        payload[field] = True
        with pytest.raises(MissionValidationError, match="unsupported adaptation/replan materialization field"):
            service.create_adaptation_replan(mission_id, payload)


def test_mission_event_trigger_requires_and_binds_exact_source_event_identity(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "event-bound")
    source_event = service.get_mission_events(mission_id)["events"][-1]
    payload = adaptation_request(
        service,
        mission_id,
        active,
        "event-bound",
        trigger_source="MISSION_EVENT",
        trigger_code="MISSION_STATE_CHANGE",
        source_event_id=source_event["event_id"],
        expected_source_event_sha256=source_event["canonical_sha256"],
        evidence_refs=[],
    )
    result = service.create_adaptation_replan(mission_id, payload)
    bound = result["source_bindings"]["source_event"]
    assert bound["event_id"] == source_event["event_id"]
    assert bound["canonical_sha256"] == source_event["canonical_sha256"]
    assert result["replan_trigger"]["source_event_bound"] is True


def test_mission_event_trigger_rejects_stale_source_event_hash(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "event-stale")
    source_event = service.get_mission_events(mission_id)["events"][-1]
    payload = adaptation_request(
        service,
        mission_id,
        active,
        "event-stale",
        trigger_source="MISSION_EVENT",
        trigger_code="MISSION_STATE_CHANGE",
        source_event_id=source_event["event_id"],
        expected_source_event_sha256="0" * 64,
        evidence_refs=[],
    )
    with pytest.raises(MissionConcurrencyConflict, match="source Mission event hash"):
        service.create_adaptation_replan(mission_id, payload)


def test_non_event_trigger_requires_explicit_evidence_reference(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "no-evidence")
    payload = adaptation_request(service, mission_id, active, "no-evidence", evidence_refs=[])
    with pytest.raises(MissionValidationError, match="requires at least one evidence_refs"):
        service.create_adaptation_replan(mission_id, payload)


def test_exact_replay_is_idempotent_and_does_not_duplicate_contract_or_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "replay")
    payload = adaptation_request(service, mission_id, active, "replay")
    first = service.create_adaptation_replan(mission_id, payload)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_adaptation_replan(mission_id, payload)
    assert replay["idempotent_replay"] is True
    assert replay["adaptation_episode_id"] == first["adaptation_episode_id"]
    assert replay["replan_trigger_id"] == first["replan_trigger_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_adaptation_replan_history(mission_id)["adaptation_episode_count"] == 1
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_idempotency_key_conflict_rejects_different_detection_material(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "conflict")
    payload = adaptation_request(service, mission_id, active, "conflict")
    service.create_adaptation_replan(mission_id, payload)
    changed = deepcopy(payload)
    changed["evidence_refs"] = ["operator-ticket:changed"]
    with pytest.raises(MissionAdaptationReplanConflict, match="idempotency_key"):
        service.create_adaptation_replan(mission_id, changed)


def test_contract_and_detection_event_survive_service_restart(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active = provision_running(service, "restart")
    created = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "restart")
    )
    restarted = make_service(db)
    loaded = restarted.get_adaptation_replan(mission_id, created["adaptation_episode_id"])
    assert loaded["canonical_sha256"] == created["canonical_sha256"]
    assert loaded["detection_event"]["canonical_sha256"] == created["detection_event"]["canonical_sha256"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_repository_manifest_projects_stage371_store_and_event_lineage(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "repository")
    created = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "repository")
    )
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_adaptation_replan_contracts"] == 1
    episodes = repo["persistence_manifest"]["canonical_adaptation_replan_store"]["episodes"]
    assert episodes == [{
        "adaptation_episode_id": created["adaptation_episode_id"],
        "replan_trigger_id": created["replan_trigger_id"],
        "source_plan_version_record_id": created["source_plan_version_record_id"],
        "source_plan_version": created["source_plan_version"],
        "source_plan_generation": created["source_plan_generation"],
        "target_plan_generation": created["target_plan_generation"],
        "episode_state": created["episode_state"],
        "trigger_source": created["trigger_source"],
        "trigger_code": created["trigger_code"],
        "source_event_id": None,
        "source_event_sha256": None,
        "evidence_ref_count": 1,
        "canonical_sha256": created["canonical_sha256"],
        "request_sha256": created["adaptation_replan_contract"]["provenance"]["request_sha256"],
        "idempotency_key": created["adaptation_replan_contract"]["provenance"]["idempotency_key"],
        "source_state": "RUNNING",
        "source_state_version": created["source_bindings"]["source_state_version"],
        "source_version_sha256": created["source_bindings"]["source_version_sha256"],
    }]
    assert any(x["check"] == "canonical_adaptation_replan_store" and x["status"] == "PASS" for x in repo["integrity_checks"])


def test_repository_reconstruction_detects_tampered_adaptation_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active = provision_running(service, "tamper")
    created = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "tamper")
    )
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT canonical_json FROM mission_adaptation_replan_contracts WHERE adaptation_episode_id=?",
            (created["adaptation_episode_id"],),
        ).fetchone()
        contract = json.loads(row[0])
        contract["adaptation_episode"]["episode_state"] = "COMMITTED"
        conn.execute(
            "UPDATE mission_adaptation_replan_contracts SET canonical_json=? WHERE adaptation_episode_id=?",
            (json.dumps(contract, sort_keys=True, separators=(",", ":")), created["adaptation_episode_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="canonical_adaptation_replan_store"):
        service.get_mission_repository(mission_id)


def test_http_surface_contains_stage371_routes_without_new_dispatch_route():
    source = inspect.getsource(MissionOrchestratorHandler)
    assert 'parts[3] == "adaptation-replans"' in source
    assert 'parts[3] == "adaptation-replan-definition"' in source
    assert "create_adaptation_replan" in source
    assert "APTSMissionOrchestrator/3.9.10" in MissionOrchestratorHandler.server_version

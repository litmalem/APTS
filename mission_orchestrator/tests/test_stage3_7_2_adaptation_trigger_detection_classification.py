from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import inspect
import json
import sqlite3

import pytest

from mission_orchestrator.adaptation_trigger import (
    ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY,
    ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION,
    ADAPTATION_TRIGGER_CLASSIFICATION_EVENT_TYPE,
    ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX,
    ADAPTATION_TRIGGER_CLASSIFICATION_MODE,
    ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION,
    ADAPTATION_TRIGGER_REASON_CODES,
    ADAPTATION_TRIGGER_REPLAN_SCOPE_LEVELS,
    ADAPTATION_TRIGGER_SEVERITIES,
    ADAPTATION_TRIGGER_SOURCE_STAGES,
    REPLAN_SCOPE_LEVEL_3,
    REPLAN_SCOPE_LEVEL_4,
    canonical_adaptation_trigger_classification_definition,
    verify_adaptation_trigger_classification_contract,
)
from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionAdaptationTriggerClassificationConflict,
    MissionAdaptationTriggerClassificationGuardRejected,
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_3_8_task_readiness_scheduling_projection import make_service
from tests.test_stage3_7_1_canonical_adaptation_replan_contract_identity import (
    adaptation_request,
    provision_running,
)


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PRIOR_CONTROL = "stage3.7.1-canonical-adaptation-replan-contract-identity"


def detected_episode(service, key: str, *, trigger_code: str = "TASK_FAILURE"):
    mission_id, active = provision_running(service, key)
    payload = adaptation_request(
        service,
        mission_id,
        active,
        key,
        trigger_source="OPERATOR_REQUEST",
        trigger_code=trigger_code,
        evidence_refs=[f"evidence:{key}"],
    )
    detected = service.create_adaptation_replan(mission_id, payload)
    return mission_id, active, detected


def classification_request(
    service,
    mission_id: str,
    active: dict,
    detected: dict,
    key: str,
    *,
    reason_code: str = "EXECUTION_FAILURE",
    severity: str = "HIGH",
    source_stage: str = "STAGE3_5_EXECUTION",
    **overrides,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage372-classify-{key}",
        "expected_adaptation_episode_id": detected["adaptation_episode_id"],
        "expected_replan_trigger_id": detected["replan_trigger_id"],
        "expected_adaptation_replan_sha256": detected["canonical_sha256"],
        "expected_detection_event_sha256": detected["detection_event"]["canonical_sha256"],
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "reason_code": reason_code,
        "severity": severity,
        "source_stage": source_stage,
        "classified_by": "stage3.7.2-pytest",
        "reason": "Deterministically classify an evidence-backed adaptation trigger",
        "metadata": {"stage": "3.7.2", "key": key},
    }
    body.update(overrides)
    return body


def classify(service, mission_id: str, active: dict, detected: dict, key: str, **kwargs):
    body = classification_request(service, mission_id, active, detected, key, **kwargs)
    return service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body), body


def test_health_activates_stage372_classification_and_migration_46(tmp_path):
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
    assert health["adaptation_replan_database_migration_level"] == 45
    assert health["adaptation_trigger_classification_database_migration_level"] == 46
    assert health["adaptation_trigger_classification_stage_schema_version"] == ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION
    assert health["adaptation_trigger_classification_contract_schema_version"] == ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION
    assert health["adaptation_trigger_classification_identity_prefix"] == ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX
    assert health["adaptation_trigger_classification_mode"] == ADAPTATION_TRIGGER_CLASSIFICATION_MODE
    assert health["adaptation_trigger_classification_authority"] == ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY
    assert health["adaptation_trigger_classification_persistence_store"] == "mission_adaptation_trigger_classifications"
    assert health["adaptation_trigger_classification_event_type"] == ADAPTATION_TRIGGER_CLASSIFICATION_EVENT_TYPE
    assert health["adaptation_trigger_eligibility_evaluation_performed"] is False
    assert health["adaptation_trigger_planner_invocation_performed"] is False
    assert health["adaptation_trigger_dispatch_performed"] is False
    assert health["adaptation_trigger_target_actuation"] is False


def test_definition_exposes_closed_reason_severity_source_and_scope_taxonomy(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = detected_episode(service, "definition")
    definition = service.get_adaptation_trigger_classification_definition(mission_id)[
        "adaptation_trigger_classification_definition"
    ]
    assert definition == canonical_adaptation_trigger_classification_definition()
    assert definition["reason_codes"] == list(ADAPTATION_TRIGGER_REASON_CODES)
    assert definition["severities"] == list(ADAPTATION_TRIGGER_SEVERITIES)
    assert definition["source_stages"] == list(ADAPTATION_TRIGGER_SOURCE_STAGES)
    assert definition["replan_scope_levels"] == list(ADAPTATION_TRIGGER_REPLAN_SCOPE_LEVELS)
    assert definition["unauthoritative_ai_thinks_replan_trigger_allowed"] is False
    assert definition["next_stage"] == "3.7.3"


def test_classifies_execution_failure_as_level3_partial_plan(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "level3", trigger_code="TASK_FAILURE")
    result, _ = classify(service, mission_id, active, detected, "level3")
    assert result["classification_id"].startswith(ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX)
    assert result["classification_status"] == "CLASSIFIED"
    assert result["effective_episode_state"] == "CLASSIFIED"
    assert result["source_episode_state"] == "DETECTED"
    assert result["reason_code"] == "EXECUTION_FAILURE"
    assert result["replan_scope_level"] == REPLAN_SCOPE_LEVEL_3
    assert verify_adaptation_trigger_classification_contract(result["adaptation_trigger_classification_contract"])
    assert result["classification_event"]["event_type"] == ADAPTATION_TRIGGER_CLASSIFICATION_EVENT_TYPE


def test_classifies_environment_change_as_level4_mission_scope(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "level4", trigger_code="CTI_CHANGE")
    result, _ = classify(
        service,
        mission_id,
        active,
        detected,
        "level4",
        reason_code="ENVIRONMENT_STATE_CHANGED",
        severity="CRITICAL",
        source_stage="ENVIRONMENT",
    )
    assert result["reason_code"] == "ENVIRONMENT_STATE_CHANGED"
    assert result["replan_scope_level"] == REPLAN_SCOPE_LEVEL_4
    assert result["trigger_classification"]["replan_scope"] == "MISSION_LEVEL"


def test_incompatible_stage371_trigger_refinement_is_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "incompatible", trigger_code="TASK_FAILURE")
    body = classification_request(
        service, mission_id, active, detected, "incompatible", reason_code="POLICY_CHANGED"
    )
    with pytest.raises(MissionAdaptationTriggerClassificationGuardRejected, match="incompatible"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_noncanonical_severity_is_rejected_before_persistence(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "severity")
    body = classification_request(service, mission_id, active, detected, "severity", severity="EXTREME")
    with pytest.raises(MissionValidationError, match="severity is not canonical"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)
    assert service.get_adaptation_trigger_classification_history(mission_id)["classification_count"] == 0


def test_noncanonical_source_stage_is_rejected_before_persistence(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "source-stage")
    body = classification_request(service, mission_id, active, detected, "source-stage", source_stage="LLM_GUESS")
    with pytest.raises(MissionValidationError, match="source_stage is not canonical"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_route_episode_identity_must_match_expected_episode(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "episode-route")
    body = classification_request(
        service,
        mission_id,
        active,
        detected,
        "episode-route",
        expected_adaptation_episode_id="adpt-route-mismatch",
    )
    with pytest.raises(MissionAdaptationTriggerClassificationGuardRejected, match="classification route"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_replan_trigger_identity_must_match_stage371_source(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "trigger-id")
    body = classification_request(
        service,
        mission_id,
        active,
        detected,
        "trigger-id",
        expected_replan_trigger_id="rpln-wrong",
    )
    with pytest.raises(MissionAdaptationTriggerClassificationGuardRejected, match="expected_replan_trigger_id"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_stage371_contract_hash_binding_is_mandatory(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "source-hash")
    body = classification_request(
        service,
        mission_id,
        active,
        detected,
        "source-hash",
        expected_adaptation_replan_sha256="0" * 64,
    )
    with pytest.raises(MissionConcurrencyConflict, match="contract hash"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_detection_event_hash_binding_is_mandatory(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "event-hash")
    body = classification_request(
        service,
        mission_id,
        active,
        detected,
        "event-hash",
        expected_detection_event_sha256="0" * 64,
    )
    with pytest.raises(MissionConcurrencyConflict, match="detection event hash"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_stale_expected_mission_state_or_version_is_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "stale-mission")
    body = classification_request(service, mission_id, active, detected, "stale-mission")
    stale_state = deepcopy(body)
    stale_state["idempotency_key"] = "stage372-stale-state"
    stale_state["expected_state_version"] += 1
    with pytest.raises(MissionConcurrencyConflict, match="expected_state_version"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], stale_state)
    stale_version = deepcopy(body)
    stale_version["idempotency_key"] = "stage372-stale-version"
    stale_version["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="expected_version_sha256"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], stale_version)


def test_mission_state_change_after_detection_invalidates_classification_even_with_fresh_request(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "state-drift")
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "stage372-state-drift")
    body = classification_request(service, mission_id, active, detected, "state-drift")
    with pytest.raises(MissionAdaptationTriggerClassificationGuardRejected, match="changed since Stage-3.7.1 detection"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_active_plan_head_binding_is_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "plan-head")
    body = classification_request(
        service,
        mission_id,
        active,
        detected,
        "plan-head",
        expected_active_plan_version_record_id="pver-wrong",
    )
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_request_rejects_future_authority_and_side_effect_fields(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "forbidden")
    for index, field in enumerate(
        ["eligibility", "snapshot", "lifecycle_command", "planner_output", "candidate", "plan_delta", "commit", "dispatch", "actuation"]
    ):
        body = classification_request(service, mission_id, active, detected, f"forbidden-{index}")
        body[field] = True
        with pytest.raises(MissionValidationError, match="unsupported adaptation trigger classification field"):
            service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)


def test_exact_replay_is_idempotent_without_duplicate_contract_or_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "replay")
    body = classification_request(service, mission_id, active, detected, "replay")
    first = service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)
    assert replay["idempotent_replay"] is True
    assert replay["classification_id"] == first["classification_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_adaptation_trigger_classification_history(mission_id)["classification_count"] == 1
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_idempotency_key_conflict_rejects_changed_classification_material(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "idempotency")
    body = classification_request(service, mission_id, active, detected, "idempotency")
    service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], body)
    changed = deepcopy(body)
    changed["severity"] = "CRITICAL"
    with pytest.raises(MissionAdaptationTriggerClassificationConflict, match="idempotency_key"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], changed)


def test_one_adaptation_episode_accepts_exactly_one_classification(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "one-per-episode")
    first = classification_request(service, mission_id, active, detected, "one-per-episode")
    service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], first)
    second = classification_request(
        service,
        mission_id,
        active,
        detected,
        "one-per-episode-second",
        reason_code="TASK_OUTCOME_REJECTED",
    )
    with pytest.raises(MissionAdaptationTriggerClassificationConflict, match="already classified"):
        service.classify_adaptation_trigger(mission_id, detected["adaptation_episode_id"], second)


def test_classification_survives_service_restart_and_read_surfaces(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active, detected = detected_episode(service, "restart")
    created, _ = classify(service, mission_id, active, detected, "restart")
    restarted = make_service(db)
    loaded = restarted.get_adaptation_trigger_classification(mission_id, created["classification_id"])
    by_episode = restarted.get_adaptation_trigger_classification_for_episode(mission_id, detected["adaptation_episode_id"])
    assert loaded["canonical_sha256"] == created["canonical_sha256"]
    assert by_episode["classification_id"] == created["classification_id"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_repository_manifest_projects_classification_store_and_lineage(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "repository")
    created, _ = classify(service, mission_id, active, detected, "repository")
    repo = service.get_mission_repository(mission_id)
    assert repo["record_counts"]["mission_adaptation_replan_contracts"] == 1
    assert repo["record_counts"]["mission_adaptation_trigger_classifications"] == 1
    projected = repo["persistence_manifest"]["adaptation_trigger_classification_store"]["classifications"]
    assert projected[0]["classification_id"] == created["classification_id"]
    assert projected[0]["source_adaptation_replan_sha256"] == detected["canonical_sha256"]
    assert any(x["check"] == "adaptation_trigger_classification_store" and x["status"] == "PASS" for x in repo["integrity_checks"])


def test_repository_reconstruction_detects_tampered_classification_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active, detected = detected_episode(service, "tamper")
    created, _ = classify(service, mission_id, active, detected, "tamper")
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT canonical_json FROM mission_adaptation_trigger_classifications WHERE classification_id=?",
            (created["classification_id"],),
        ).fetchone()
        contract = json.loads(row[0])
        contract["trigger_classification"]["severity"] = "LOW"
        conn.execute(
            "UPDATE mission_adaptation_trigger_classifications SET canonical_json=? WHERE classification_id=?",
            (json.dumps(contract, sort_keys=True, separators=(",", ":")), created["classification_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="adaptation_trigger_classification_store"):
        service.get_mission_repository(mission_id)


def test_classification_preserves_stage371_detection_and_all_authority_boundaries(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, detected = detected_episode(service, "immutable")
    before_state = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    before_versions = deepcopy(service.get_plan_version_history(mission_id)["plan_versions"])
    created, _ = classify(service, mission_id, active, detected, "immutable")
    source = service.get_adaptation_replan(mission_id, detected["adaptation_episode_id"])
    assert source["episode_state"] == "DETECTED"
    assert source["adaptation_replan_contract"]["canonical_sha256"] == detected["canonical_sha256"]
    assert source["effective_episode_state"] == "CLASSIFIED"
    assert source["trigger_classification"]["classification_id"] == created["classification_id"]
    assert service.get_mission_state(mission_id)["mission_state"] == before_state
    assert service.get_plan_version_history(mission_id)["plan_versions"] == before_versions
    boundary = created["authority_boundary"]
    assert all(
        boundary[name] is False
        for name in (
            "classification_is_replan_eligibility",
            "classification_is_replan_authorization",
            "classification_is_lifecycle_replan_command",
            "classification_is_planner_invocation",
            "classification_is_successor_plan",
            "classification_is_plan_supersession",
            "historical_plan_mutation_performed",
            "terminal_state_reopening_performed",
            "mission_state_transition_performed",
            "governance_query_performed",
            "runtime_query_performed",
            "runtime_control_io_performed",
            "dispatch_performed",
            "new_execution_attempt_created",
            "external_network_io_performed",
            "target_action_dispatch_performed",
            "target_actuation",
        )
    )
    source_code = inspect.getsource(MissionOrchestratorHandler)
    assert "adaptation-trigger-classifications" in source_code
    assert "adaptation-trigger-classification-definition" in source_code
    assert 'parts[5] == "classification"' in source_code

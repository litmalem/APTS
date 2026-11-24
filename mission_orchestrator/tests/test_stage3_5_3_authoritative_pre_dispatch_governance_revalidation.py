from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDispatchEligibilityNotFound,
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
    MissionPreDispatchGovernanceConflict,
    MissionPreDispatchGovernanceGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.pre_dispatch_governance import (
    EXECUTION_AUTHORIZED_STATUS,
    EXECUTION_DENIED_STATUS,
    EXECUTION_REVIEW_STATUS,
    PRE_DISPATCH_REVALIDATION_ID_PREFIX,
    PRE_DISPATCH_REVALIDATION_MODE,
    PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION,
    canonical_pre_dispatch_revalidation_definition,
    verify_pre_dispatch_revalidation_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_5_2_dispatch_eligibility_execution_preconditions import make_service, materialize_gate

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR_351 = "stage3.5.1-canonical-execution-dispatch-contract-identity"
PREDECESSOR_352 = "stage3.5.2-dispatch-eligibility-execution-preconditions"
PREDECESSOR_353 = "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"


def revalidation_request(service, mission_id: str, active: dict, dispatch: dict, gate: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage353-revalidation-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
        "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
        "expected_dispatch_eligibility_id": gate["dispatch_eligibility_id"],
        "expected_dispatch_eligibility_sha256": gate["canonical_sha256"],
        "requested_by": "stage3.5.3-pytest",
        "reason": "Authoritative pre-dispatch Governance revalidation only",
        "metadata": {"stage": "3.5.3", "key": key},
    }
    body.update(overrides)
    return body


def prepared(service, key: str):
    mission_id, active, route, authorization, delegation, delivery, dispatch, gate, _ = materialize_gate(service, key)
    body = revalidation_request(service, mission_id, active, dispatch, gate, key)
    return mission_id, active, route, authorization, delegation, delivery, dispatch, gate, body


def test_01_health_activates_stage353_and_preserves_predecessors(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][40:50] == [PREDECESSOR_351, PREDECESSOR_352, PREDECESSOR_353, "stage3.5.4-idempotent-dispatch-execution-attempt-identity", "stage3.5.5-dispatch-delivery-execution-acknowledgement", "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["pre_dispatch_governance_revalidation_schema_version"] == PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION
    assert health["pre_dispatch_governance_revalidation_mode"] == PRE_DISPATCH_REVALIDATION_MODE
    assert health["pre_dispatch_governance_database_migration_level"] == 29
    assert health["pre_dispatch_governance_persistence_store"] == "mission_pre_dispatch_governance_revalidations"
    assert "mission_pre_dispatch_governance_revalidations" in REPOSITORY_STORES


def test_02_definition_expresses_authoritative_but_non_dispatching_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = prepared(service, "definition")
    definition = service.get_pre_dispatch_revalidation_definition(mission_id)[
        "authoritative_pre_dispatch_governance_revalidation_definition"
    ]
    assert definition == canonical_pre_dispatch_revalidation_definition()
    assert definition["requires_stage351_execution_dispatch_contract"] is True
    assert definition["requires_stage352_passed_dispatch_eligibility"] is True
    assert definition["governance_query_performed"] is True
    assert definition["fresh_authoritative_policy_decision_required"] is True
    assert definition["allow_grants_execution_authorization"] is True
    assert definition["execution_authorization_is_dispatch"] is False
    assert definition["dispatch_performed"] is False
    assert definition["target_actuation"] is False


def test_03_allow_materializes_xreval_and_execution_authorization_only(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, body = prepared(service, "allow")
    result = service.authorize_pre_dispatch_execution(mission_id, body)
    assert result["pre_dispatch_revalidation_id"].startswith(PRE_DISPATCH_REVALIDATION_ID_PREFIX)
    assert result["plan_version_record_id"] == active["plan_version_record_id"]
    assert result["execution_dispatch_id"] == dispatch["execution_dispatch_id"]
    assert result["dispatch_eligibility_id"] == gate["dispatch_eligibility_id"]
    assert result["governance_decision"] == "ALLOW"
    assert result["execution_authorization_status"] == EXECUTION_AUTHORIZED_STATUS
    assert result["execution_authorized"] is True
    assert result["eligible_for_execution"] is True
    assert result["dispatch_authorized"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False
    assert verify_pre_dispatch_revalidation_contract(result["pre_dispatch_revalidation_contract"])


def test_04_new_revalidation_performs_exactly_one_fresh_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "fresh-query")
    before = gov.evaluate_calls
    service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before + 1
    request = gov.requests[-1]
    assert request["action_class"] == "TASK_EXECUTION"
    assert request["action_name"] == "AUTHORIZE_EXECUTION_DISPATCH"
    assert request["context"]["dispatch_requested"] is False
    assert request["context"]["runtime_endpoint_requested"] is False
    assert request["context"]["target_actuation_requested"] is False


def test_05_governance_deny_is_persisted_fail_closed(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "deny")
    gov.emergency_stop = True
    result = service.authorize_pre_dispatch_execution(mission_id, body)
    assert result["governance_decision"] == "DENY"
    assert result["execution_authorization_status"] == EXECUTION_DENIED_STATUS
    assert result["execution_authorized"] is False
    assert result["eligible_for_execution"] is False
    assert result["dispatch_performed"] is False


def test_06_review_or_human_approval_is_fail_closed(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "review")
    original = gov.evaluate_authorization

    def review(payload):
        response = original(payload)
        response["decision"] = "REVIEW"
        response["requires_human_approval"] = True
        return response

    gov.evaluate_authorization = review
    result = service.authorize_pre_dispatch_execution(mission_id, body)
    assert result["governance_decision"] == "REVIEW"
    assert result["execution_authorization_status"] == EXECUTION_REVIEW_STATUS
    assert result["execution_authorized"] is False
    assert result["dispatch_performed"] is False


def test_07_caller_cannot_supply_authority_or_execution_side_effect_fields(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "forbidden")
    for field, value in (
        ("governance_decision", "ALLOW"),
        ("execution_authorized", True),
        ("runtime_endpoint", "http://127.0.0.1"),
        ("dispatch_performed", True),
        ("target_actuation", True),
    ):
        candidate = dict(body)
        candidate[field] = value
        with pytest.raises(MissionValidationError, match="unsupported pre-dispatch"):
            service.authorize_pre_dispatch_execution(mission_id, candidate)


def test_08_stale_state_version_is_rejected_before_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "stale-state")
    before = gov.evaluate_calls
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict, match="state_version"):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before


def test_09_stale_version_vector_is_rejected_before_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "stale-vector")
    before = gov.evaluate_calls
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before


def test_10_stale_active_plan_hash_is_rejected_before_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "stale-plan")
    before = gov.evaluate_calls
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active_plan_sha256"):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before


def test_11_unknown_stage352_eligibility_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "unknown-xelig")
    body["expected_dispatch_eligibility_id"] = "xelig-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionDispatchEligibilityNotFound):
        service.authorize_pre_dispatch_execution(mission_id, body)


def test_12_stale_stage352_eligibility_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "stale-xelig")
    body["expected_dispatch_eligibility_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="dispatch_eligibility_sha256"):
        service.authorize_pre_dispatch_execution(mission_id, body)


def test_13_idempotent_replay_does_not_duplicate_governance_query_row_or_event(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "replay")
    first = service.authorize_pre_dispatch_execution(mission_id, body)
    calls = gov.evaluate_calls
    events_before = [e for e in service.repository.list_mission_events(mission_id) if e["event_type"] == "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED"]
    second = service.authorize_pre_dispatch_execution(mission_id, body)
    events_after = [e for e in service.repository.list_mission_events(mission_id) if e["event_type"] == "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED"]
    assert second["idempotent_replay"] is True
    assert second["pre_dispatch_revalidation_id"] == first["pre_dispatch_revalidation_id"]
    assert gov.evaluate_calls == calls
    assert len(service.repository.list_pre_dispatch_revalidations(mission_id)) == 1
    assert len(events_after) == len(events_before) == 1


def test_14_idempotency_key_reuse_with_changed_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "idem-conflict")
    service.authorize_pre_dispatch_execution(mission_id, body)
    changed = dict(body)
    changed["reason"] = "changed"
    with pytest.raises(MissionPreDispatchGovernanceConflict):
        service.authorize_pre_dispatch_execution(mission_id, changed)


def test_15_repeated_new_revalidations_are_append_only_and_sequenced(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, body1 = prepared(service, "sequence")
    before = gov.evaluate_calls
    first = service.authorize_pre_dispatch_execution(mission_id, body1)
    body2 = revalidation_request(service, mission_id, active, dispatch, gate, "sequence-2")
    second = service.authorize_pre_dispatch_execution(mission_id, body2)
    assert first["revalidation_sequence"] == 1
    assert second["revalidation_sequence"] == 2
    assert first["pre_dispatch_revalidation_id"] != second["pre_dispatch_revalidation_id"]
    assert gov.evaluate_calls == before + 2
    assert [x["revalidation_sequence"] for x in service.repository.list_pre_dispatch_revalidations(mission_id, gate["dispatch_eligibility_id"])] == [1, 2]


def test_16_response_loss_after_governance_commit_recovers_without_duplicate_authority_call(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "response-loss")
    before = gov.evaluate_calls
    gov.fail_evaluate_after_commit_once = True
    with pytest.raises(MissionGovernanceUnavailable):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before + 1
    assert service.repository.list_pre_dispatch_revalidations(mission_id) == []
    recovered = service.authorize_pre_dispatch_execution(mission_id, body)
    assert recovered["execution_authorized"] is True
    assert gov.evaluate_calls == before + 1
    assert len(service.repository.list_pre_dispatch_revalidations(mission_id)) == 1


def test_17_canonical_state_change_before_revalidation_fails_before_authority_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "state-change")
    before = gov.evaluate_calls
    execute(service, mission_id, "PAUSE", "stage353-pause-before-revalidation")
    with pytest.raises(MissionPreDispatchGovernanceGuardRejected, match="RUNNING"):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before


def test_18_authoritative_scope_drift_fails_closed(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "scope-drift")
    gov.scopes[-1]["version"] = int(gov.scopes[-1]["version"]) + 1
    with pytest.raises(MissionGovernanceProtocolError, match="scope"):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert service.repository.list_pre_dispatch_revalidations(mission_id) == []


def test_19_repository_projection_and_tamper_detection_cover_xreval(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body = prepared(service, "integrity")
    result = service.authorize_pre_dispatch_execution(mission_id, body)
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_pre_dispatch_governance_revalidations"] == 1
    refs = view["persistence_manifest"]["authoritative_pre_dispatch_governance_revalidation_store"]["revalidations"]
    assert refs[0]["pre_dispatch_revalidation_id"] == result["pre_dispatch_revalidation_id"]

    conn = sqlite3.connect(service.repository.sqlite_path)
    try:
        conn.execute(
            "UPDATE mission_pre_dispatch_governance_revalidations SET canonical_sha256=? WHERE pre_dispatch_revalidation_id=?",
            ("0" * 64, result["pre_dispatch_revalidation_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="authoritative_pre_dispatch"):
        service.get_mission_repository(mission_id)


def test_20_action_class_follows_capability_and_unmapped_stays_fail_closed():
    from mission_orchestrator.pre_dispatch_governance import pre_dispatch_action_class
    assert pre_dispatch_action_class("pentest.recon") == "TARGET_RECON"
    assert pre_dispatch_action_class("pentest.validate") == "VULNERABILITY_VALIDATION"
    assert pre_dispatch_action_class("cti.analyze.context") == "CTI_SOURCE_READ"
    assert pre_dispatch_action_class("unknown.capability") == "TASK_EXECUTION"

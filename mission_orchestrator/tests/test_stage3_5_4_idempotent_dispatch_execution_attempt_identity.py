from __future__ import annotations

import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDispatchEligibilityNotFound,
    MissionExecutionAttemptConflict,
    MissionExecutionAttemptGuardRejected,
    MissionExecutionDispatchNotFound,
    MissionPreDispatchGovernanceNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.execution_attempt import (
    DISPATCH_COMMIT_STATUS,
    DISPATCH_ENVELOPE_ID_PREFIX,
    EXECUTION_ATTEMPT_AUTHORITY,
    EXECUTION_ATTEMPT_ID_PREFIX,
    EXECUTION_ATTEMPT_MODE,
    EXECUTION_ATTEMPT_SCHEMA_VERSION,
    EXECUTION_ATTEMPT_STATUS,
    canonical_execution_attempt_definition,
    verify_execution_attempt_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation import (
    make_service,
    prepared,
    revalidation_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR_351 = "stage3.5.1-canonical-execution-dispatch-contract-identity"
PREDECESSOR_352 = "stage3.5.2-dispatch-eligibility-execution-preconditions"
PREDECESSOR_353 = "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"


def attempt_request(service, mission_id: str, active: dict, dispatch: dict, gate: dict, reval: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage354-attempt-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
        "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
        "expected_dispatch_eligibility_id": gate["dispatch_eligibility_id"],
        "expected_dispatch_eligibility_sha256": gate["canonical_sha256"],
        "expected_pre_dispatch_revalidation_id": reval["pre_dispatch_revalidation_id"],
        "expected_pre_dispatch_revalidation_sha256": reval["canonical_sha256"],
        "created_by": "stage3.5.4-pytest",
        "reason": "Commit idempotent dispatch attempt identity only; delivery remains Stage 3.5.5",
        "metadata": {"stage": "3.5.4", "key": key},
    }
    body.update(overrides)
    return body


def committed(service, key: str):
    mission_id, active, route, authorization, delegation, delivery, dispatch, gate, reval_body = prepared(service, key)
    reval = service.authorize_pre_dispatch_execution(mission_id, reval_body)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, key)
    result = service.commit_execution_attempt(mission_id, body)
    return mission_id, active, route, authorization, delegation, delivery, dispatch, gate, reval, body, result


def test_01_health_activates_stage354_and_preserves_execution_control_lineage(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][40:50] == [PREDECESSOR_351, PREDECESSOR_352, PREDECESSOR_353, "stage3.5.4-idempotent-dispatch-execution-attempt-identity", "stage3.5.5-dispatch-delivery-execution-acknowledgement", "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["execution_attempt_schema_version"] == EXECUTION_ATTEMPT_SCHEMA_VERSION
    assert health["execution_attempt_mode"] == EXECUTION_ATTEMPT_MODE
    assert health["execution_attempt_authority"] == EXECUTION_ATTEMPT_AUTHORITY
    assert health["execution_attempt_database_migration_level"] == 30
    assert health["execution_attempt_persistence_store"] == "mission_execution_attempts"
    assert "mission_execution_attempts" in REPOSITORY_STORES


def test_02_definition_is_durable_commit_only_and_defers_delivery_to_355(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = prepared(service, "definition")
    definition = service.get_execution_attempt_definition(mission_id)["idempotent_dispatch_execution_attempt_definition"]
    assert definition == canonical_execution_attempt_definition()
    assert definition["requires_stage351_execution_dispatch_contract"] is True
    assert definition["requires_stage352_passed_dispatch_eligibility"] is True
    assert definition["requires_latest_stage353_allow_execution_authorization"] is True
    assert definition["durable_dispatch_commit_performed"] is True
    assert definition["immutable_dispatch_envelope_materialized"] is True
    assert definition["target_delivery_performed"] is False
    assert definition["execution_started"] is False
    assert definition["target_actuation"] is False
    assert definition["next_stage"] == "3.5.5"


def test_03_happy_path_materializes_stable_attempt_and_envelope_without_delivery(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    *_, result = committed(service, "happy")
    assert result["execution_attempt_id"].startswith(EXECUTION_ATTEMPT_ID_PREFIX)
    assert result["dispatch_envelope_id"].startswith(DISPATCH_ENVELOPE_ID_PREFIX)
    assert result["attempt_ordinal"] == 1
    assert result["dispatch_commit_status"] == DISPATCH_COMMIT_STATUS
    assert result["execution_attempt_status"] == EXECUTION_ATTEMPT_STATUS
    assert result["execution_authorized"] is True
    assert result["eligible_for_delivery"] is True
    assert result["eligible_for_execution_start"] is False
    assert result["target_delivery_performed"] is False
    assert result["execution_started"] is False
    assert result["target_actuation"] is False
    assert verify_execution_attempt_contract(result["execution_attempt_contract"])


def test_04_commit_reuses_latest_allow_and_performs_no_new_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, reval_body = prepared(service, "no-governance-query")
    reval = service.authorize_pre_dispatch_execution(mission_id, reval_body)
    calls = gov.evaluate_calls
    result = service.commit_execution_attempt(
        mission_id, attempt_request(service, mission_id, active, dispatch, gate, reval, "no-governance-query")
    )
    assert result["pre_dispatch_revalidation_id"] == reval["pre_dispatch_revalidation_id"]
    assert result["governance_query_performed"] is False
    assert gov.evaluate_calls == calls


def test_05_older_allow_becomes_ineligible_when_latest_revalidation_is_deny(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, allow_body = prepared(service, "latest-deny")
    allow = service.authorize_pre_dispatch_execution(mission_id, allow_body)
    gov.emergency_stop = True
    deny = service.authorize_pre_dispatch_execution(
        mission_id, revalidation_request(service, mission_id, active, dispatch, gate, "latest-deny-2")
    )
    assert deny["governance_decision"] == "DENY"
    with pytest.raises(MissionExecutionAttemptGuardRejected, match="latest"):
        service.commit_execution_attempt(
            mission_id, attempt_request(service, mission_id, active, dispatch, gate, allow, "latest-deny-old")
        )
    with pytest.raises(MissionExecutionAttemptGuardRejected, match="does not authorize"):
        service.commit_execution_attempt(
            mission_id, attempt_request(service, mission_id, active, dispatch, gate, deny, "latest-deny-current")
        )


def test_06_latest_review_or_human_approval_is_fail_closed(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, body = prepared(service, "review")
    original = gov.evaluate_authorization

    def review(payload):
        response = original(payload)
        response["decision"] = "REVIEW"
        response["requires_human_approval"] = True
        return response

    gov.evaluate_authorization = review
    reval = service.authorize_pre_dispatch_execution(mission_id, body)
    assert reval["governance_decision"] == "REVIEW"
    with pytest.raises(MissionExecutionAttemptGuardRejected, match="does not authorize"):
        service.commit_execution_attempt(
            mission_id, attempt_request(service, mission_id, active, dispatch, gate, reval, "review")
        )


def test_07_stale_state_version_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "stale-state")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict, match="state_version"):
        service.commit_execution_attempt(mission_id, body)


def test_08_stale_version_vector_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "stale-vector")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "stale-vector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.commit_execution_attempt(mission_id, body)


def test_09_stale_active_plan_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "stale-plan")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "stale-plan")
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active_plan_sha256"):
        service.commit_execution_attempt(mission_id, body)


def test_10_unknown_execution_dispatch_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "unknown-dispatch")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "unknown-dispatch")
    body["expected_execution_dispatch_id"] = "xdispatch-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionExecutionDispatchNotFound):
        service.commit_execution_attempt(mission_id, body)


def test_11_stale_execution_dispatch_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "stale-dispatch")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "stale-dispatch")
    body["expected_execution_dispatch_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="execution_dispatch_sha256"):
        service.commit_execution_attempt(mission_id, body)


def test_12_unknown_or_stale_dispatch_eligibility_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "eligibility")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "eligibility")
    body["expected_dispatch_eligibility_id"] = "xelig-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionDispatchEligibilityNotFound):
        service.commit_execution_attempt(mission_id, body)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "eligibility-hash")
    body["expected_dispatch_eligibility_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="dispatch_eligibility_sha256"):
        service.commit_execution_attempt(mission_id, body)


def test_13_unknown_or_stale_pre_dispatch_revalidation_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "revalidation")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "revalidation")
    body["expected_pre_dispatch_revalidation_id"] = "xreval-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionPreDispatchGovernanceNotFound):
        service.commit_execution_attempt(mission_id, body)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "revalidation-hash")
    body["expected_pre_dispatch_revalidation_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="pre_dispatch_revalidation_sha256"):
        service.commit_execution_attempt(mission_id, body)


def test_14_idempotent_replay_returns_same_attempt_and_does_not_duplicate_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body, first = committed(service, "replay")
    second = service.commit_execution_attempt(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["execution_attempt_id"] == first["execution_attempt_id"]
    assert second["dispatch_envelope_id"] == first["dispatch_envelope_id"]
    assert len(service.repository.list_execution_attempts(mission_id)) == 1
    events = [e for e in service.repository.list_mission_events(mission_id) if e["event_type"] == "MISSION_EXECUTION_ATTEMPT_COMMITTED"]
    assert len(events) == 1


def test_15_idempotency_key_reuse_with_changed_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, body, _ = committed(service, "idem-conflict")
    changed = dict(body)
    changed["reason"] = "changed canonical request"
    with pytest.raises(MissionExecutionAttemptConflict, match="idempotency_key"):
        service.commit_execution_attempt(mission_id, changed)


def test_16_different_idempotency_key_cannot_create_second_initial_attempt_for_dispatch(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, reval, _, _ = committed(service, "second-attempt")
    body2 = attempt_request(service, mission_id, active, dispatch, gate, reval, "second-attempt-2")
    with pytest.raises(MissionExecutionAttemptConflict, match="already has"):
        service.commit_execution_attempt(mission_id, body2)
    assert len(service.repository.list_execution_attempts(mission_id)) == 1


def test_17_caller_cannot_supply_identity_delivery_or_execution_side_effect_fields(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "forbidden")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    base = attempt_request(service, mission_id, active, dispatch, gate, reval, "forbidden")
    for field, value in (
        ("execution_attempt_id", "xattempt-forged"),
        ("dispatch_envelope_id", "xenv-forged"),
        ("runtime_endpoint", "http://127.0.0.1:9999"),
        ("target_delivery_performed", True),
        ("delivery_acknowledged", True),
        ("execution_started", True),
        ("target_actuation", True),
    ):
        candidate = dict(base)
        candidate[field] = value
        with pytest.raises(MissionValidationError, match="unsupported execution attempt"):
            service.commit_execution_attempt(mission_id, candidate)


def test_18_state_change_before_commit_is_fail_closed_and_creates_no_attempt(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch, gate, rb = prepared(service, "state-change")
    reval = service.authorize_pre_dispatch_execution(mission_id, rb)
    body = attempt_request(service, mission_id, active, dispatch, gate, reval, "state-change")
    execute(service, mission_id, "PAUSE", "stage354-pause-before-commit")
    with pytest.raises(MissionExecutionAttemptGuardRejected, match="RUNNING"):
        service.commit_execution_attempt(mission_id, body)
    assert service.repository.list_execution_attempts(mission_id) == []


def test_19_repository_projection_and_tamper_detection_cover_execution_attempt(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, result = committed(service, "integrity")
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_execution_attempts"] == 1
    refs = view["persistence_manifest"]["idempotent_dispatch_execution_attempt_store"]["attempts"]
    assert refs[0]["execution_attempt_id"] == result["execution_attempt_id"]

    conn = sqlite3.connect(service.repository.sqlite_path)
    try:
        conn.execute(
            "UPDATE mission_execution_attempts SET canonical_sha256=? WHERE execution_attempt_id=?",
            ("0" * 64, result["execution_attempt_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="idempotent_dispatch_execution_attempt"):
        service.get_mission_repository(mission_id)


def test_20_attempt_identity_is_durable_across_service_restart_and_history_read(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, *_, result = committed(service, "restart")
    attempt_id = result["execution_attempt_id"]
    envelope_id = result["dispatch_envelope_id"]

    restarted, _ = make_service(db)
    fetched = restarted.get_execution_attempt(mission_id, attempt_id)
    history = restarted.get_execution_attempt_history(mission_id)
    assert fetched["execution_attempt_id"] == attempt_id
    assert fetched["dispatch_envelope_id"] == envelope_id
    assert fetched["target_delivery_performed"] is False
    assert history["execution_attempt_count"] == 1
    assert history["execution_attempts"][0]["execution_attempt_id"] == attempt_id

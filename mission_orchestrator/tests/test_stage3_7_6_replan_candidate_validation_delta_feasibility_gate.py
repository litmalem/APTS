from __future__ import annotations

import inspect
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionReplanCandidateNotFound,
    MissionReplanValidationConflict,
    MissionReplanValidationGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.replan_validation import (
    REPLAN_VALIDATION_AUTHORITY,
    REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION,
    REPLAN_VALIDATION_EVENT_TYPE,
    REPLAN_VALIDATION_ID_PREFIX,
    REPLAN_VALIDATION_MODE,
    REPLAN_VALIDATION_STAGE_SCHEMA_VERSION,
    REPLAN_VALIDATION_STATUS_REJECTED,
    REPLAN_VALIDATION_STATUS_VALIDATED,
    canonical_replan_validation_definition,
    evaluate_replan_candidate_feasibility,
    verify_replan_validation_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_7_5_deterministic_replan_candidate_generation import (
    generate,
    make_governed_service,
    stage375_source,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def source(service, key: str):
    args, snapshot = stage375_source(service, key)
    candidate, _ = generate(service, args[0], snapshot, key)
    return args, snapshot, candidate


def validation_request(candidate, key: str, **overrides):
    c = candidate["replan_candidate_contract"]
    src = c["source_bindings"]
    body = {
        "idempotency_key": f"stage376-validation-{key}",
        "expected_replan_candidate_id": candidate["replan_candidate_id"],
        "expected_replan_candidate_sha256": candidate["canonical_sha256"],
        "expected_candidate_payload_sha256": candidate["candidate_payload_sha256"],
        "expected_replan_snapshot_id": candidate["replan_snapshot_id"],
        "expected_replan_snapshot_sha256": src["replan_snapshot_sha256"],
        "expected_source_plan_version_record_id": src["source_plan_version_record_id"],
        "expected_source_plan_version": src["source_plan_version"],
        "expected_source_plan_sha256": src["source_plan_sha256"],
        "expected_source_state_version": src["source_state_version"],
        "expected_source_version_sha256": src["source_version_sha256"],
        "validated_by": "stage3.7.6-pytest",
        "reason": "Validate immutable deterministic replan delta",
        "metadata": {"stage": "3.7.6", "key": key},
    }
    body.update(overrides)
    return body


def validate(service, mission_id, candidate, key: str, **overrides):
    body = validation_request(candidate, key, **overrides)
    return service.validate_replan_candidate(mission_id, candidate["replan_candidate_id"], body), body


def test_health_activates_stage376_and_migration_50(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["replan_validation_database_migration_level"] == 50
    assert h["replan_validation_stage_schema_version"] == REPLAN_VALIDATION_STAGE_SCHEMA_VERSION
    assert h["replan_validation_contract_schema_version"] == REPLAN_VALIDATION_CONTRACT_SCHEMA_VERSION
    assert h["replan_validation_identity_prefix"] == REPLAN_VALIDATION_ID_PREFIX
    assert h["replan_validation_persistence_store"] == "mission_replan_decisions"
    assert "mission_replan_decisions" in REPOSITORY_STORES


def test_definition_exposes_fail_closed_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, _ = source(service, "definition")
    d = service.get_replan_validation_definition(args[0])["replan_candidate_validation_delta_feasibility_definition"]
    assert d == canonical_replan_validation_definition()
    assert d["requires_stage375_candidate"] is True
    assert d["deterministic_reproduction_required"] is True
    assert d["replan_decision_committed"] is False
    assert d["next_stage"] == "3.7.7"


def test_validation_materializes_validated_for_commit_decision(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "materialize")
    result, _ = validate(service, args[0], candidate, "materialize")
    assert result["replan_validation_id"].startswith(REPLAN_VALIDATION_ID_PREFIX)
    assert result["validation_status"] == REPLAN_VALIDATION_STATUS_VALIDATED
    assert result["feasible"] is True
    assert result["failed_check_count"] == 0


def test_validation_contract_self_verifies(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "verify")
    result, _ = validate(service, args[0], candidate, "verify")
    assert verify_replan_validation_contract(result["replan_validation_contract"])
    assert result["replan_validation_contract"]["authority_boundary"]["authority"] == REPLAN_VALIDATION_AUTHORITY
    assert result["replan_validation_contract"]["authority_boundary"]["mode"] == REPLAN_VALIDATION_MODE


def test_validation_records_canonical_event(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "event")
    result, _ = validate(service, args[0], candidate, "event")
    assert result["validation_event"]["event_type"] == REPLAN_VALIDATION_EVENT_TYPE
    assert result["validation_event"]["causation_id"] == result["replan_validation_id"]


def test_validation_checks_exact_next_plan_version_and_generation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot, candidate = source(service, "version")
    result, _ = validate(service, args[0], candidate, "version")
    src = candidate["replan_candidate_contract"]["source_bindings"]
    decision_src = result["replan_validation_contract"]["source_bindings"]
    assert decision_src["candidate_plan_version"] == src["source_plan_version"] + 1
    assert decision_src["candidate_plan_generation"] == snapshot["replan_snapshot_contract"]["source_bindings"]["target_plan_generation"]


def test_validation_performs_no_commit_supersession_dispatch_or_actuation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "boundary")
    before_state = deepcopy(service.get_mission_state(args[0])["mission_state"])
    before_history = deepcopy(service.get_plan_version_history(args[0]))
    result, _ = validate(service, args[0], candidate, "boundary")
    assert result["plan_validation_performed"] is True
    assert result["delta_feasibility_evaluated"] is True
    assert result["successor_plan_created"] is False
    assert result["replan_decision_committed"] is False
    assert result["plan_supersession_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False
    assert service.get_mission_state(args[0])["mission_state"] == before_state
    assert service.get_plan_version_history(args[0]) == before_history


def test_validation_performs_no_additional_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "no-governance")
    before = fake.evaluate_calls
    result, _ = validate(service, args[0], candidate, "no-governance")
    assert fake.evaluate_calls == before
    assert result["governance_query_performed"] is False
    assert result["external_context_refresh_performed"] is False


def test_idempotent_replay_returns_same_decision(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "idempotent")
    first, body = validate(service, args[0], candidate, "idempotent")
    second = service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)
    assert second["idempotent_replay"] is True
    assert second["replan_validation_id"] == first["replan_validation_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]


def test_idempotency_key_reuse_with_different_request_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "idem-conflict")
    _, body = validate(service, args[0], candidate, "idem-conflict")
    body["reason"] = "changed"
    with pytest.raises(MissionReplanValidationConflict, match="different request material"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_only_one_validation_decision_per_candidate(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "one-decision")
    validate(service, args[0], candidate, "one-decision")
    body = validation_request(candidate, "one-decision-second")
    with pytest.raises(MissionReplanValidationConflict, match="already has"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_stale_candidate_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "stale-candidate")
    body = validation_request(candidate, "stale-candidate", expected_replan_candidate_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="ReplanCandidate hash"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_stale_candidate_payload_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "stale-payload")
    body = validation_request(candidate, "stale-payload", expected_candidate_payload_sha256="1" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="candidate payload hash"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_stale_snapshot_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "stale-snapshot")
    body = validation_request(candidate, "stale-snapshot", expected_replan_snapshot_sha256="2" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="ReplanSnapshot hash"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_stale_source_plan_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "stale-plan")
    body = validation_request(candidate, "stale-plan", expected_source_plan_sha256="3" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="source Plan hash"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_stale_source_version_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "stale-version")
    body = validation_request(candidate, "stale-version", expected_source_version_sha256="4" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="source Mission version hash"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_route_candidate_identity_mismatch_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "route-mismatch")
    body = validation_request(candidate, "route-mismatch", expected_replan_candidate_id="rpcand-not-the-route")
    with pytest.raises(MissionReplanValidationGuardRejected, match="route"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_caller_supplied_feasibility_override_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "forbidden")
    body = validation_request(candidate, "forbidden")
    body["feasible"] = True
    with pytest.raises(MissionValidationError, match="unsupported replan candidate validation"):
        service.validate_replan_candidate(args[0], candidate["replan_candidate_id"], body)


def test_missing_candidate_is_reported(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "missing")
    body = validation_request(candidate, "missing")
    body["expected_replan_candidate_id"] = "rpcand-missing"
    with pytest.raises(MissionReplanCandidateNotFound):
        service.validate_replan_candidate(args[0], "rpcand-missing", body)


def test_persistence_table_contains_decision_and_exact_contract(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    args, _, candidate = source(service, "persistence")
    result, _ = validate(service, args[0], candidate, "persistence")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM mission_replan_decisions WHERE replan_validation_id=?", (result["replan_validation_id"],)).fetchone()
        assert row is not None
        assert row["validation_status"] == REPLAN_VALIDATION_STATUS_VALIDATED
        assert row["canonical_sha256"] == result["canonical_sha256"]
    finally:
        conn.close()


def test_history_and_candidate_lookup_return_decision(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "lookup")
    result, _ = validate(service, args[0], candidate, "lookup")
    assert service.get_replan_validation_history(args[0])["replan_validation_count"] == 1
    by_candidate = service.get_replan_validation_for_candidate(args[0], candidate["replan_candidate_id"])
    assert by_candidate["replan_validation_id"] == result["replan_validation_id"]
    by_id = service.get_replan_validation(args[0], result["replan_validation_id"])
    assert by_id["canonical_sha256"] == result["canonical_sha256"]


def test_pure_feasibility_gate_accepts_canonical_candidate(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    _, snapshot, candidate = source(service, "pure")
    result = evaluate_replan_candidate_feasibility(candidate["replan_candidate_contract"], snapshot["replan_snapshot_contract"])
    assert result["feasible"] is True
    assert result["rejection_codes"] == []
    assert all(x["passed"] for x in result["findings"])


def test_pure_feasibility_gate_rejects_integrity_tamper(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    _, snapshot, candidate = source(service, "tamper")
    tampered = deepcopy(candidate["replan_candidate_contract"])
    tampered["candidate_successor_plan"]["candidate_plan_version"] += 1
    result = evaluate_replan_candidate_feasibility(tampered, snapshot["replan_snapshot_contract"])
    assert result["feasible"] is False
    assert "CANDIDATE_INTEGRITY" in result["rejection_codes"]


def test_api_surface_exposes_stage376_get_and_post_routes():
    source_text = inspect.getsource(MissionOrchestratorHandler)
    assert '"replan-validations"' in source_text
    assert '"replan-candidate-validation-delta-feasibility-definition"' in source_text
    assert "validate_replan_candidate" in source_text
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"


def test_repository_model_and_boundary_keep_commit_for_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _, candidate = source(service, "boundary-next")
    result, _ = validate(service, args[0], candidate, "boundary-next")
    boundary = result["replan_validation_contract"]["authority_boundary"]
    assert result["validation_status"] in {REPLAN_VALIDATION_STATUS_VALIDATED, REPLAN_VALIDATION_STATUS_REJECTED}
    assert boundary["validated_for_commit"] is True
    assert boundary["replan_decision_committed"] is False
    assert boundary["successor_plan_created"] is False
    assert canonical_replan_validation_definition()["next_stage"] == "3.7.7"

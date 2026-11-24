from __future__ import annotations

import inspect
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionGovernanceUnavailable,
    MissionReplanCommitConflict,
    MissionReplanCommitGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.replan_commit import (
    REPLAN_COMMIT_AUTHORITY,
    REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION,
    REPLAN_COMMIT_EVENT_TYPE,
    REPLAN_COMMIT_GOVERNANCE_ACTION_CLASS,
    REPLAN_COMMIT_GOVERNANCE_ACTION_NAME,
    REPLAN_COMMIT_GOVERNANCE_RESOURCE_TYPE,
    REPLAN_COMMIT_ID_PREFIX,
    REPLAN_COMMIT_MODE,
    REPLAN_COMMIT_STAGE_SCHEMA_VERSION,
    REPLAN_COMMIT_STATUS,
    canonical_replan_commit_definition,
    verify_replan_commit_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_1_4_governance_authorization_binding import binding_payload, scope_payload
from tests.test_stage3_7_3_replan_eligibility_governance_gate import PolicyGovernanceClient
from tests.test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate import (
    make_governed_service,
    source,
    validate,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def stage377_source(service, key: str):
    args, snapshot, candidate = source(service, key)
    mission_id = args[0]
    validation, _ = validate(service, mission_id, candidate, key)
    return mission_id, snapshot, candidate, validation


def commit_request(snapshot, candidate, validation, key: str, **overrides):
    snap = snapshot["replan_snapshot_contract"]
    src = validation["replan_validation_contract"]["source_bindings"]
    body = {
        "idempotency_key": f"stage377-commit-{key}",
        "expected_replan_validation_id": validation["replan_validation_id"],
        "expected_replan_validation_sha256": validation["canonical_sha256"],
        "expected_replan_candidate_id": candidate["replan_candidate_id"],
        "expected_replan_candidate_sha256": candidate["canonical_sha256"],
        "expected_candidate_payload_sha256": candidate["candidate_payload_sha256"],
        "expected_replan_snapshot_id": snapshot["replan_snapshot_id"],
        "expected_replan_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_source_plan_version_record_id": src["source_plan_version_record_id"],
        "expected_source_plan_version": src["source_plan_version"],
        "expected_source_plan_sha256": src["source_plan_sha256"],
        "expected_source_state_version": src["source_state_version"],
        "expected_source_version_sha256": src["source_version_sha256"],
        "expected_scope_snapshot_id": snap["scope_context"]["mission_scope_snapshot_id"],
        "expected_scope_sha256": snap["scope_context"]["mission_scope_sha256"],
        "expected_governance_binding_snapshot_id": snap["governance_context"]["governance_binding_snapshot_id"],
        "expected_governance_binding_version": snap["governance_context"]["governance_binding_version"],
        "expected_governance_binding_sha256": snap["governance_context"]["governance_binding_sha256"],
        "requested_by": "stage3.7.7-pytest",
        "reason": "Authorize validated replan and atomically materialize successor Plan version",
        "metadata": {"stage": "3.7.7", "key": key},
    }
    body.update(overrides)
    return body


def commit(service, mission_id, snapshot, candidate, validation, key: str, **overrides):
    body = commit_request(snapshot, candidate, validation, key, **overrides)
    return service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body), body


def test_health_activates_stage377_and_migration_51(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["replan_commit_database_migration_level"] == 51
    assert h["replan_commit_stage_schema_version"] == REPLAN_COMMIT_STAGE_SCHEMA_VERSION
    assert h["replan_commit_contract_schema_version"] == REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION
    assert h["replan_commit_identity_prefix"] == REPLAN_COMMIT_ID_PREFIX
    assert h["replan_commit_persistence_store"] == "mission_replan_commits"
    assert h["supported_controls"][66:70] == [
        "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization",
        "stage3.7.8-atomic-replan-commit-supersession-handoff",
        "stage3.7.9-adapt-replan-lineage-replay-recovery",
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
    ]
    assert h["supported_controls"][-1] == CONTROL
    assert "mission_replan_commits" in REPOSITORY_STORES


def test_definition_declares_authoritative_commit_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _ = stage377_source(service, "definition")
    d = service.get_replan_commit_definition(mission_id)[
        "authoritative_replan_commit_authorization_successor_plan_materialization_definition"
    ]
    assert d == canonical_replan_commit_definition()
    assert d["authoritative_governance_revalidation_performed"] is True
    assert d["atomic_successor_plan_materialization_and_head_cas"] is True
    assert d["mission_state_transition_performed"] is False
    assert d["dispatch_performed"] is False
    assert d["target_actuation"] is False
    assert d["next_stage"] == "3.7.8"


def test_authorized_commit_materializes_exact_successor_and_advances_head(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "materialize")
    before = service.get_plan_version_history(mission_id)
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "materialize")
    after = service.get_plan_version_history(mission_id)
    assert result["replan_commit_id"].startswith(REPLAN_COMMIT_ID_PREFIX)
    assert result["commit_status"] == REPLAN_COMMIT_STATUS
    assert result["predecessor_plan_version"] == before["active_head"]["active_plan_version"]
    assert result["successor_plan_version"] == result["predecessor_plan_version"] + 1
    assert after["active_head"]["active_plan_version_record_id"] == result["successor_plan_version_record_id"]
    assert after["active_head"]["active_plan_sha256"] == result["successor_plan_sha256"]
    assert after["version_count"] == before["version_count"] + 1


def test_commit_contract_self_verifies_and_binds_all_sources(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "contract")
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "contract")
    c = result["replan_commit_contract"]
    assert verify_replan_commit_contract(c)
    assert c["authority_boundary"]["authority"] == REPLAN_COMMIT_AUTHORITY
    assert c["authority_boundary"]["mode"] == REPLAN_COMMIT_MODE
    assert c["source_bindings"]["replan_validation_sha256"] == validation["canonical_sha256"]
    assert c["source_bindings"]["replan_candidate_sha256"] == candidate["canonical_sha256"]
    assert c["source_bindings"]["replan_snapshot_sha256"] == snapshot["canonical_sha256"]


def test_commit_performs_one_authoritative_governance_revalidation_with_exact_action(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "governance")
    before = fake.evaluate_calls
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "governance")
    assert fake.evaluate_calls == before + 1
    request = fake.requests[-1]
    assert request["action_class"] == REPLAN_COMMIT_GOVERNANCE_ACTION_CLASS
    assert request["action_name"] == REPLAN_COMMIT_GOVERNANCE_ACTION_NAME
    assert request["resource_type"] == REPLAN_COMMIT_GOVERNANCE_RESOURCE_TYPE
    assert request["resource_value"] == mission_id
    assert request["context"]["replan_validation_id"] == validation["replan_validation_id"]
    assert request["context"]["mission_state_transition_requested"] is False
    assert request["context"]["dispatch_requested"] is False
    assert result["authoritative_governance_revalidation_performed"] is True
    assert result["governance_query_performed"] is True


def test_predecessor_remains_append_only_and_is_effectively_superseded(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "append-only")
    before = service.get_plan_version_history(mission_id)
    predecessor = deepcopy(before["plan_versions"][-1])
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "append-only")
    after = service.get_plan_version_history(mission_id)
    stored_predecessor = [x for x in after["plan_versions"] if x["plan_version_record_id"] == predecessor["plan_version_record_id"]][0]
    assert stored_predecessor["canonical_sha256"] == predecessor["canonical_sha256"]
    assert result["historical_plan_mutation_performed"] is False
    assert result["plan_supersession_performed"] is True


def test_commit_does_not_transition_mission_or_route_dispatch_or_actuate(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "boundary")
    before_state = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "boundary")
    after_state = service.get_mission_state(mission_id)["mission_state"]
    assert after_state == before_state
    assert result["mission_state_transition_performed"] is False
    assert result["routing_performed"] is False
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False


def test_commit_records_commit_and_plan_supersession_events(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "events")
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "events")
    assert result["commit_event"]["event_type"] == REPLAN_COMMIT_EVENT_TYPE
    assert result["commit_event"]["causation_id"] == result["replan_commit_id"]
    assert result["plan_supersession_event"]["event_type"] == "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED"
    assert result["plan_supersession_event"]["causation_id"] == result["successor_plan_version_record_id"]


def test_exact_idempotent_replay_reuses_commit_and_does_not_requery_governance(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "idempotent")
    first, body = commit(service, mission_id, snapshot, candidate, validation, "idempotent")
    before = fake.evaluate_calls
    second = service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert second["idempotent_replay"] is True
    assert second["replan_commit_id"] == first["replan_commit_id"]
    assert second["successor_plan_version_record_id"] == first["successor_plan_version_record_id"]
    assert fake.evaluate_calls == before
    assert service.get_plan_version_history(mission_id)["version_count"] == 2


def test_idempotency_key_reuse_with_different_material_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "idem-conflict")
    _, body = commit(service, mission_id, snapshot, candidate, validation, "idem-conflict")
    body["reason"] = "different request material"
    with pytest.raises(MissionReplanCommitConflict, match="different request material"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)


def test_only_one_authoritative_commit_per_validation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "one-commit")
    commit(service, mission_id, snapshot, candidate, validation, "one-commit")
    body = commit_request(snapshot, candidate, validation, "one-commit-second")
    with pytest.raises(MissionReplanCommitConflict, match="already has"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)


def test_stale_validation_hash_fails_closed_before_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "stale-validation")
    before = fake.evaluate_calls
    body = commit_request(snapshot, candidate, validation, "stale-validation", expected_replan_validation_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="ReplanValidation hash"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert fake.evaluate_calls == before


def test_stale_source_plan_hash_fails_closed_before_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "stale-plan")
    before = fake.evaluate_calls
    body = commit_request(snapshot, candidate, validation, "stale-plan", expected_source_plan_sha256="1" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="source_plan_sha256"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert fake.evaluate_calls == before


def test_scope_drift_after_snapshot_fails_closed_without_governance_commit_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "scope-drift")
    updated = scope_payload("scope-drift-v2", expected=1)
    if "INTERNAL_REASONING" not in updated["roe"]["allowed_action_classes"]:
        updated["roe"]["allowed_action_classes"].append("INTERNAL_REASONING")
    service.put_mission_scope_contract(mission_id, updated)
    before = fake.evaluate_calls
    body = commit_request(snapshot, candidate, validation, "scope-drift")
    with pytest.raises(MissionConcurrencyConflict, match="Mission state/version changed|Mission scope changed"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert fake.evaluate_calls == before


def test_governance_binding_drift_after_snapshot_fails_closed_without_commit_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "binding-drift")
    service.put_mission_governance_binding(mission_id, binding_payload("binding-drift-v2", expected=1))
    before = fake.evaluate_calls
    body = commit_request(snapshot, candidate, validation, "binding-drift")
    with pytest.raises(MissionConcurrencyConflict, match="Mission state/version changed|Governance binding changed"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert fake.evaluate_calls == before


def test_governance_deny_prevents_any_successor_plan_or_commit_row(tmp_path):
    fake = PolicyGovernanceClient(decision="ALLOW")
    service, fake = make_governed_service(tmp_path / "missions.db", fake=fake)
    mission_id, snapshot, candidate, validation = stage377_source(service, "deny")
    fake.forced_decision = "DENY"
    before_history = deepcopy(service.get_plan_version_history(mission_id))
    body = commit_request(snapshot, candidate, validation, "deny")
    with pytest.raises(MissionReplanCommitGuardRejected, match="did not authorize"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    after_history = service.get_plan_version_history(mission_id)
    assert after_history == before_history
    assert service.repository.list_replan_commits(mission_id) == []


def test_governance_review_human_approval_prevents_materialization(tmp_path):
    fake = PolicyGovernanceClient(decision="ALLOW", requires_human_approval=False)
    service, fake = make_governed_service(tmp_path / "missions.db", fake=fake)
    mission_id, snapshot, candidate, validation = stage377_source(service, "review")
    fake.forced_requires_human_approval = True
    before = service.get_plan_version_history(mission_id)["version_count"]
    body = commit_request(snapshot, candidate, validation, "review")
    with pytest.raises(MissionReplanCommitGuardRejected, match="without human approval"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert service.get_plan_version_history(mission_id)["version_count"] == before
    assert service.repository.list_replan_commits(mission_id) == []


def test_governance_response_loss_is_recovered_without_duplicate_authorization_request(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "response-loss")
    body = commit_request(snapshot, candidate, validation, "response-loss")
    fake.fail_evaluate_after_commit_once = True
    before = fake.evaluate_calls
    with pytest.raises(MissionGovernanceUnavailable):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert fake.evaluate_calls == before + 1
    assert service.repository.list_replan_commits(mission_id) == []
    result = service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)
    assert result["commit_status"] == REPLAN_COMMIT_STATUS
    assert fake.evaluate_calls == before + 1


def test_caller_cannot_supply_successor_plan_or_governance_outcome(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "forbidden")
    body = commit_request(snapshot, candidate, validation, "forbidden")
    body["successor_plan"] = {"tasks": []}
    with pytest.raises(MissionValidationError, match="unsupported authoritative replan commit"):
        service.commit_authorized_replan(mission_id, validation["replan_validation_id"], body)


def test_persistence_table_contains_exact_commit_and_atomic_successor(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    mission_id, snapshot, candidate, validation = stage377_source(service, "persistence")
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "persistence")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM mission_replan_commits WHERE replan_commit_id=?", (result["replan_commit_id"],)).fetchone()
        plan = conn.execute("SELECT * FROM mission_plan_versions WHERE plan_version_record_id=?", (result["successor_plan_version_record_id"],)).fetchone()
        head = conn.execute("SELECT * FROM mission_plan_version_heads WHERE mission_id=?", (mission_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None and row["canonical_sha256"] == result["canonical_sha256"]
    assert plan is not None and plan["canonical_sha256"] == result["successor_plan_sha256"]
    assert head is not None and head["active_plan_version_record_id"] == result["successor_plan_version_record_id"]


def test_repository_reconstruction_includes_and_verifies_stage377_commit(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, snapshot, candidate, validation = stage377_source(service, "repository")
    result, _ = commit(service, mission_id, snapshot, candidate, validation, "repository")
    recovered = service.get_mission_repository(mission_id)
    manifest = recovered["persistence_manifest"]
    commits = manifest["authoritative_replan_commit_store"]["commits"]
    assert manifest["repository_migration_level"] == 53
    assert manifest["record_counts"]["mission_replan_commits"] == 1
    assert commits[0]["replan_commit_id"] == result["replan_commit_id"]
    assert commits[0]["successor_plan_sha256"] == result["successor_plan_sha256"]


def test_api_surface_exposes_stage377_get_post_history_and_definition_routes():
    source_text = inspect.getsource(MissionOrchestratorHandler)
    assert '"replan-commits"' in source_text
    assert '"authoritative-replan-commit-successor-plan-materialization-definition"' in source_text
    assert "commit_authorized_replan" in source_text
    assert "get_replan_commit_for_validation" in source_text
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"

from __future__ import annotations

from copy import deepcopy
import inspect
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionAdaptationTriggerClassificationNotFound,
    MissionConcurrencyConflict,
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
    MissionReplanEligibilityGovernanceConflict,
    MissionReplanEligibilityGovernanceGuardRejected,
    MissionReplanEligibilityGovernanceNotFound,
    MissionValidationError,
)
from mission_orchestrator.replan_eligibility import (
    REPLAN_ELIGIBILITY_AUTHORITY,
    REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION,
    REPLAN_ELIGIBILITY_EVENT_TYPE,
    REPLAN_ELIGIBILITY_ID_PREFIX,
    REPLAN_ELIGIBILITY_MODE,
    REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION,
    REPLAN_GOVERNANCE_ACTION_CLASS,
    REPLAN_GOVERNANCE_ACTION_NAME,
    REPLAN_GOVERNANCE_RESOURCE_TYPE,
    canonical_replan_eligibility_definition,
    verify_replan_eligibility_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_4_governance_authorization_binding import (
    FakeGovernanceClient,
    binding_payload,
    scope_payload,
)
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_7_1_canonical_adaptation_replan_contract_identity import (
    adaptation_request,
    provision_running,
)
from tests.test_stage3_7_2_adaptation_trigger_detection_classification import classification_request


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PRIOR_371 = "stage3.7.1-canonical-adaptation-replan-contract-identity"
PRIOR_372 = "stage3.7.2-adaptation-trigger-detection-classification"
PRIOR_373 = "stage3.7.3-replan-eligibility-governance-gate"


class PolicyGovernanceClient(FakeGovernanceClient):
    def __init__(self, *, decision: str = "ALLOW", requires_human_approval: bool = False):
        super().__init__()
        self.forced_decision = decision
        self.forced_requires_human_approval = requires_human_approval

    def evaluate_authorization(self, payload):
        response = super().evaluate_authorization(payload)
        response["decision"] = self.forced_decision
        response["requires_human_approval"] = self.forced_requires_human_approval
        response["approval_request_id"] = (
            "approval-test-1" if self.forced_requires_human_approval else None
        )
        hash_body = {k: v for k, v in response.items() if k not in {"decision_hash", "decision_status", "governance_event_id"}}
        response["decision_hash"] = self._hash(hash_body)
        if self.decisions:
            persisted = {k: v for k, v in response.items() if k != "governance_event_id"}
            persisted["decision_status"] = "ACTIVE"
            self.decisions[-1] = persisted
        if self.events:
            event_id = response["governance_event_id"]
            self.events[-1]["payload"] = {**self.decisions[-1], "governance_event_id": event_id}
        return response


def make_governed_service(db_path, fake=None):
    fake = fake or FakeGovernanceClient()
    service = CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db_path)),
        governance_client=fake,
    )
    return service, fake


def classified_governed_episode(service, key: str):
    mission_id, active = provision_running(service, key)
    scope_body = scope_payload(f"scope-{key}")
    if "INTERNAL_REASONING" not in scope_body["roe"]["allowed_action_classes"]:
        scope_body["roe"]["allowed_action_classes"].append("INTERNAL_REASONING")
    scope = service.put_mission_scope_contract(mission_id, scope_body)
    binding = service.put_mission_governance_binding(mission_id, binding_payload(f"bind-{key}"))
    detected = service.create_adaptation_replan(
        mission_id,
        adaptation_request(
            service,
            mission_id,
            active,
            key,
            trigger_source="OPERATOR_REQUEST",
            trigger_code="TASK_FAILURE",
            evidence_refs=[f"evidence:{key}"],
        ),
    )
    classification = service.classify_adaptation_trigger(
        mission_id,
        detected["adaptation_episode_id"],
        classification_request(service, mission_id, active, detected, key),
    )
    return mission_id, active, scope, binding, detected, classification


def eligibility_request(service, mission_id, active, scope, binding, detected, classification, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage373-eligibility-{key}",
        "expected_adaptation_episode_id": detected["adaptation_episode_id"],
        "expected_classification_id": classification["classification_id"],
        "expected_adaptation_replan_sha256": detected["canonical_sha256"],
        "expected_classification_sha256": classification["canonical_sha256"],
        "expected_classification_event_sha256": classification["classification_event"]["canonical_sha256"],
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_scope_snapshot_id": scope["snapshot_id"],
        "expected_scope_sha256": scope["canonical_sha256"],
        "expected_governance_binding_snapshot_id": binding["binding_snapshot_id"],
        "expected_governance_binding_version": binding["binding_version"],
        "expected_governance_binding_sha256": binding["canonical_sha256"],
        "requested_by": "stage3.7.3-pytest",
        "reason": "Evaluate deterministic replan eligibility under authoritative Governance",
        "metadata": {"stage": "3.7.3", "key": key},
    }
    body.update(overrides)
    return body


def evaluate(service, mission_id, active, scope, binding, detected, classification, key: str, **overrides):
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, key, **overrides)
    return service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body), body


def test_health_activates_stage373_gate_and_migration_47(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == [PRIOR_371, PRIOR_372, PRIOR_373, "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["adaptation_replan_database_migration_level"] == 45
    assert health["adaptation_trigger_classification_database_migration_level"] == 46
    assert health["replan_eligibility_database_migration_level"] == 47
    assert health["replan_eligibility_stage_schema_version"] == REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION
    assert health["replan_eligibility_contract_schema_version"] == REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION
    assert health["replan_eligibility_identity_prefix"] == REPLAN_ELIGIBILITY_ID_PREFIX
    assert health["replan_eligibility_mode"] == REPLAN_ELIGIBILITY_MODE
    assert health["replan_eligibility_authority"] == REPLAN_ELIGIBILITY_AUTHORITY
    assert health["replan_eligibility_event_type"] == REPLAN_ELIGIBILITY_EVENT_TYPE
    assert health["replan_eligibility_governance_action_class"] == REPLAN_GOVERNANCE_ACTION_CLASS
    assert health["replan_eligibility_governance_action_name"] == REPLAN_GOVERNANCE_ACTION_NAME
    assert health["replan_eligibility_governance_resource_type"] == REPLAN_GOVERNANCE_RESOURCE_TYPE
    assert health["replan_eligibility_persistence_store"] == "mission_replan_eligibility_governance_gates"
    assert "mission_replan_eligibility_governance_gates" in REPOSITORY_STORES
    assert health["replan_eligibility_static_fail_closed_before_governance_query"] is True
    assert health["replan_eligibility_lifecycle_replan_requested"] is False
    assert health["replan_eligibility_planner_invocation_performed"] is False
    assert health["replan_eligibility_plan_supersession_performed"] is False
    assert health["replan_eligibility_dispatch_performed"] is False
    assert health["replan_eligibility_target_actuation"] is False


def test_definition_exposes_authority_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, *_ = classified_governed_episode(service, "definition")
    definition = service.get_replan_eligibility_definition(mission_id)["replan_eligibility_governance_definition"]
    assert definition == canonical_replan_eligibility_definition()
    assert definition["one_gate_per_adaptation_episode"] is True
    assert definition["static_fail_closed_before_governance_query"] is True
    assert definition["governance_action_name"] == "AUTHORIZE_REPLAN"
    assert definition["lifecycle_replan_requested"] is False
    assert definition["planner_invocation_performed"] is False
    assert definition["plan_supersession_performed"] is False
    assert definition["next_stage"] == "3.7.4"


def test_allow_materializes_eligible_gate_without_replanning_side_effects(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "allow")
    state_before = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    plans_before = service.get_plan_version_history(mission_id)
    result, _ = evaluate(service, mission_id, active, scope, binding, detected, classification, "allow")
    assert result["eligibility_gate_id"].startswith(REPLAN_ELIGIBILITY_ID_PREFIX)
    assert result["static_eligibility_status"] == "PASSED"
    assert result["eligibility_status"] == "ELIGIBLE"
    assert result["replan_eligible"] is True
    assert result["effective_episode_state"] == "ELIGIBLE"
    assert result["governance_decision"] == "ALLOW"
    assert fake.evaluate_calls == 1
    assert verify_replan_eligibility_contract(result["replan_eligibility_governance_contract"])
    assert result["eligibility_event"]["event_type"] == REPLAN_ELIGIBILITY_EVENT_TYPE
    assert service.get_mission_state(mission_id)["mission_state"] == state_before
    assert service.get_plan_version_history(mission_id) == plans_before
    assert result["lifecycle_replan_requested"] is False
    assert result["replan_snapshot_bound"] is False
    assert result["planner_invocation_performed"] is False
    assert result["replan_decision_committed"] is False
    assert result["plan_supersession_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False


def test_deny_materializes_not_eligible_gate(tmp_path):
    fake = FakeGovernanceClient()
    fake.emergency_stop = True
    service, fake = make_governed_service(tmp_path / "missions.db", fake)
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "deny")
    result, _ = evaluate(service, mission_id, active, scope, binding, detected, classification, "deny")
    assert result["eligibility_status"] == "NOT_ELIGIBLE"
    assert result["replan_eligible"] is False
    assert result["effective_episode_state"] == "CLASSIFIED"
    assert result["governance_decision"] == "DENY"
    assert fake.evaluate_calls == 1


@pytest.mark.parametrize(
    ("decision", "requires_approval"),
    [("REVIEW", False), ("ALLOW", True)],
)
def test_review_or_human_approval_requirement_is_review_required(tmp_path, decision, requires_approval):
    fake = PolicyGovernanceClient(decision=decision, requires_human_approval=requires_approval)
    service, _ = make_governed_service(tmp_path / f"{decision}-{requires_approval}.db", fake)
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(
        service, f"review-{decision}-{requires_approval}"
    )
    result, _ = evaluate(
        service, mission_id, active, scope, binding, detected, classification, f"review-{decision}-{requires_approval}"
    )
    assert result["eligibility_status"] == "REVIEW_REQUIRED"
    assert result["replan_eligible"] is False
    assert result["effective_episode_state"] == "CLASSIFIED"


def test_stale_classification_hash_and_event_hash_fail_before_governance(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "stale-class")
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "stale-class")
    body["expected_classification_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="classification hash"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0

    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "stale-event")
    body["expected_classification_event_sha256"] = "1" * 64
    with pytest.raises(MissionConcurrencyConflict, match="classification event hash"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0


def test_state_drift_fails_static_eligibility_before_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "state-drift")
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "stage373-state-drift")
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "state-drift")
    with pytest.raises(MissionReplanEligibilityGovernanceGuardRejected, match="static replan eligibility failed closed"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0
    assert service.get_replan_eligibility_history(mission_id)["eligibility_gate_count"] == 0


def test_scope_change_invalidates_binding_and_fails_before_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "scope-drift")
    scope2 = scope_payload("scope-drift-v2", expected=1, max_actions=30)
    scope2["roe"]["allowed_action_classes"].append("INTERNAL_REASONING")
    current_scope = service.put_mission_scope_contract(mission_id, scope2)
    body = eligibility_request(
        service,
        mission_id,
        active,
        current_scope,
        binding,
        detected,
        classification,
        "scope-drift",
    )
    with pytest.raises(MissionReplanEligibilityGovernanceGuardRejected, match="Governance binding is stale"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0


def test_stale_scope_or_binding_expectations_fail_closed_before_governance(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "stale-binding")
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "stale-scope")
    body["expected_scope_sha256"] = "2" * 64
    with pytest.raises(MissionConcurrencyConflict, match="Mission scope changed"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "stale-binding")
    body["expected_governance_binding_sha256"] = "3" * 64
    with pytest.raises(MissionConcurrencyConflict, match="Governance binding changed"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0


def test_missing_stage372_classification_is_not_eligible_for_evaluation(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active = provision_running(service, "no-classification")
    scope_body = scope_payload("scope-no-classification")
    scope_body["roe"]["allowed_action_classes"].append("INTERNAL_REASONING")
    scope = service.put_mission_scope_contract(mission_id, scope_body)
    binding = service.put_mission_governance_binding(mission_id, binding_payload("bind-no-classification"))
    detected = service.create_adaptation_replan(
        mission_id, adaptation_request(service, mission_id, active, "no-classification", trigger_code="TASK_FAILURE")
    )
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": "stage373-missing-classification",
        "expected_adaptation_episode_id": detected["adaptation_episode_id"],
        "expected_classification_id": "rcls-missing",
        "expected_adaptation_replan_sha256": detected["canonical_sha256"],
        "expected_classification_sha256": "0" * 64,
        "expected_classification_event_sha256": "0" * 64,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_scope_snapshot_id": scope["snapshot_id"],
        "expected_scope_sha256": scope["canonical_sha256"],
        "expected_governance_binding_snapshot_id": binding["binding_snapshot_id"],
        "expected_governance_binding_version": binding["binding_version"],
        "expected_governance_binding_sha256": binding["canonical_sha256"],
        "requested_by": "stage3.7.3-pytest",
        "metadata": {},
    }
    with pytest.raises(MissionAdaptationTriggerClassificationNotFound):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0


def test_caller_cannot_supply_eligibility_planner_or_supersession_authority(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "forbidden")
    for field, value in (
        ("replan_eligible", True),
        ("governance_decision", "ALLOW"),
        ("lifecycle_replan_requested", True),
        ("planner_output", {"tasks": []}),
        ("plan_supersession", {"from": 1, "to": 2}),
        ("dispatch", True),
    ):
        body = eligibility_request(
            service, mission_id, active, scope, binding, detected, classification, f"forbidden-{field}"
        )
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported replan eligibility/governance field"):
            service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 0


def test_exact_retry_is_idempotent_and_does_not_duplicate_governance_query_or_event(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "retry")
    first, body = evaluate(service, mission_id, active, scope, binding, detected, classification, "retry")
    second = service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert second["idempotent_replay"] is True
    assert second["eligibility_gate_id"] == first["eligibility_gate_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert fake.evaluate_calls == 1
    assert service.get_replan_eligibility_history(mission_id)["eligibility_gate_count"] == 1
    events = [
        e for e in service.repository.list_mission_events(mission_id)
        if e["event_type"] == REPLAN_ELIGIBILITY_EVENT_TYPE
    ]
    assert len(events) == 1


def test_idempotency_conflict_and_one_gate_per_episode_are_enforced(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "conflict")
    result, body = evaluate(service, mission_id, active, scope, binding, detected, classification, "conflict")
    conflicting = deepcopy(body)
    conflicting["reason"] = "different request material"
    with pytest.raises(MissionReplanEligibilityGovernanceConflict, match="idempotency_key"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], conflicting)
    second_key = deepcopy(body)
    second_key["idempotency_key"] = "stage373-another-key-same-episode"
    with pytest.raises(MissionReplanEligibilityGovernanceConflict, match="already has"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], second_key)
    assert result["eligibility_gate_id"].startswith("rpelig-")
    assert fake.evaluate_calls == 1


def test_governance_response_loss_is_recovered_without_duplicate_external_decision(tmp_path):
    fake = FakeGovernanceClient()
    fake.fail_evaluate_after_commit_once = True
    service, fake = make_governed_service(tmp_path / "missions.db", fake)
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "recover")
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "recover")
    with pytest.raises(MissionGovernanceUnavailable):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 1
    recovered = service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert recovered["eligibility_status"] == "ELIGIBLE"
    assert fake.evaluate_calls == 1
    assert service.get_replan_eligibility_history(mission_id)["eligibility_gate_count"] == 1


def test_malformed_governance_decision_is_fail_closed_and_not_persisted(tmp_path):
    fake = FakeGovernanceClient()
    fake.malformed_decision = True
    service, fake = make_governed_service(tmp_path / "missions.db", fake)
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "malformed")
    body = eligibility_request(service, mission_id, active, scope, binding, detected, classification, "malformed")
    with pytest.raises(MissionGovernanceProtocolError, match="scope_contract_id mismatch"):
        service.evaluate_replan_eligibility(mission_id, detected["adaptation_episode_id"], body)
    assert fake.evaluate_calls == 1
    assert service.get_replan_eligibility_history(mission_id)["eligibility_gate_count"] == 0


def test_restart_retrieval_and_repository_integrity_include_stage373_store(tmp_path):
    db = tmp_path / "missions.db"
    service, fake = make_governed_service(db)
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, "restart")
    result, _ = evaluate(service, mission_id, active, scope, binding, detected, classification, "restart")
    restarted, _ = make_governed_service(db, fake)
    got = restarted.get_replan_eligibility(mission_id, result["eligibility_gate_id"])
    by_episode = restarted.get_replan_eligibility_for_episode(mission_id, detected["adaptation_episode_id"])
    assert got["canonical_sha256"] == result["canonical_sha256"]
    assert by_episode["eligibility_gate_id"] == result["eligibility_gate_id"]
    repo = restarted.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["persistence_manifest"]["replan_eligibility_governance_store"]["gates"][0]["eligibility_gate_id"] == result["eligibility_gate_id"]
    assert repo["record_counts"]["mission_replan_eligibility_governance_gates"] == 1


def test_not_found_and_sqlite_schema_constraints(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    mission_id, *_ = classified_governed_episode(service, "schema")
    with pytest.raises(MissionReplanEligibilityGovernanceNotFound):
        service.get_replan_eligibility(mission_id, "rpelig-missing")
    con = sqlite3.connect(db)
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='mission_replan_eligibility_governance_gates'"
    ).fetchone()[0]
    con.close()
    assert "classification_id TEXT NOT NULL UNIQUE" in sql
    assert "adaptation_episode_id TEXT NOT NULL UNIQUE" in sql
    assert "replan_trigger_id TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE(mission_id, idempotency_key)" in sql


def test_http_surface_preserves_stage373_routes_with_stage377_commit_surface(tmp_path):
    source = inspect.getsource(MissionOrchestratorHandler)
    assert 'parts[3] == "replan-eligibility-gates"' in source
    assert 'parts[3] == "replan-eligibility-governance-definition"' in source
    assert 'parts[5] == "eligibility"' in source
    assert "evaluate_replan_eligibility" in source
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert 'parts[3] == "replan-commits"' in source
    assert 'parts[3] == "replan-validations"' in source
    assert 'parts[5] == "commit"' in source
    assert "commit_authorized_replan" in source
    assert "replan-supersession" not in source

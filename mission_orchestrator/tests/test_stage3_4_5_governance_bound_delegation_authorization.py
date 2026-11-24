from __future__ import annotations

import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.delegation_authorization import (
    AUTH_STATUS_AUTHORIZED,
    AUTH_STATUS_DENIED,
    DELEGATION_ACTION_CLASS,
    DELEGATION_AUTH_ID_PREFIX,
    DELEGATION_AUTH_MODE,
    DELEGATION_AUTH_SCHEMA_VERSION,
    canonical_delegation_authorization_definition,
    verify_delegation_authorization_contract,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDelegationAuthorizationConflict,
    MissionDelegationAuthorizationGuardRejected,
    MissionGovernanceBindingNotFound,
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_1_4_governance_authorization_binding import (
    FakeGovernanceClient,
    binding_payload,
    scope_payload,
)
from tests.test_stage3_4_4_deterministic_route_selection_decision_record import create_route_decision

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def make_service(path, gov=None):
    gov = gov or FakeGovernanceClient()
    return CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(path)), governance_client=gov), gov


def provision(service, key: str, *, bind_governance: bool = True, allow_cti: bool = True):
    vals = create_route_decision(service, key)
    mission_id, active, route = vals[0], vals[1], vals[-1]
    if bind_governance:
        scope = scope_payload(f"scope-345-{key}")
        binding = binding_payload(f"bind-345-{key}")
        if allow_cti:
            scope["roe"]["allowed_action_classes"].append("CTI_SOURCE_READ")
            binding["capabilities"].append({
                "capability_id": "cti.read.context", "subject_component": "CTI-A01",
                "action_class": "CTI_SOURCE_READ", "action_name": "read_context",
                "authorization_mode": "REQUIRED", "resource_types": ["CTI_SOURCE"],
                "source_allowlist": ["cti-feed-test"], "max_risk_level": "LOW",
                "requires_human_approval": False,
            })
        service.put_mission_scope_contract(mission_id, scope)
        service.put_mission_governance_binding(mission_id, binding)
    return mission_id, active, route


def auth_request(service, mission_id, active, route, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage345-dauth-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_route_decision_id": route["route_decision_id"],
        "expected_route_decision_sha256": route["canonical_sha256"],
        "planned_task_id": route["planned_task_id"],
        "requested_by": "stage3.4.5-pytest",
        "reason": "Authorize logical task delegation only through authoritative Governance",
        "metadata": {"stage": "3.4.5", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage345_and_preserves_delegation_dispatch_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][30:40] == [
        "stage3.4.1-canonical-subsystem-registry-capability-contract",
        "stage3.4.2-task-routing-intent-candidate-resolution",
        "stage3.4.3-routing-eligibility-compatibility-gate",
        "stage3.4.4-deterministic-route-selection-decision-record",
        "stage3.4.5-governance-bound-delegation-authorization",
        "stage3.4.6-canonical-delegation-contract-handoff-envelope",
        "stage3.4.7-delegation-delivery-acknowledgement-ownership",
        "stage3.4.8-retry-fallback-reassignment-conflict-control",
        "stage3.4.9-routing-delegation-event-lineage-replay-recovery",
        "stage3.4.10-routing-delegation-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["delegation_authorization_schema_version"] == DELEGATION_AUTH_SCHEMA_VERSION
    assert health["delegation_authorization_mode"] == DELEGATION_AUTH_MODE
    assert health["delegation_authorization_governance_query_enabled"] is True
    assert health["delegation_authorization_is_delegation"] is False
    assert health["task_routing_delegation_performed"] is True
    assert health["task_routing_dispatch_performed"] is False
    assert health["delegation_authorization_persistence_store"] == "mission_delegation_authorizations"
    assert "mission_delegation_authorizations" in REPOSITORY_STORES


def test_definition_is_discoverable_and_explicit_about_authority_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision(service, "definition", bind_governance=False)
    result = service.get_task_delegation_authorization_definition(mission_id)
    definition = result["task_delegation_authorization_definition"]
    assert definition == canonical_delegation_authorization_definition()
    assert definition["requires_stage344_route_decision"] is True
    assert definition["requires_current_governance_binding"] is True
    assert definition["governance_query_performed"] is True
    assert definition["authorization_is_authoritative"] is True
    assert definition["authorization_is_delegation"] is False
    assert definition["delegation_performed"] is False
    assert definition["dispatch_performed"] is False


def test_allow_policy_decision_materializes_immutable_authorization_without_delegation(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "allow")
    result = service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "allow"))
    assert result["delegation_authorization_id"].startswith(DELEGATION_AUTH_ID_PREFIX)
    assert result["authorization_status"] == AUTH_STATUS_AUTHORIZED
    assert result["authorization_granted"] is True
    assert result["selected_subsystem"] == route["selected_subsystem"]
    assert result["selected_capability"] == route["selected_capability"]
    assert result["governance_query_performed"] is True
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["execution_authorized"] is False
    assert gov.evaluate_calls == 1
    assert gov.requests[-1]["action_class"] == DELEGATION_ACTION_CLASS
    assert verify_delegation_authorization_contract(result["delegation_authorization_contract"])


def test_deny_policy_decision_is_durable_fail_closed_evidence(tmp_path):
    gov = FakeGovernanceClient(); gov.emergency_stop = True
    service, _ = make_service(tmp_path / "m.db", gov)
    mission_id, active, route = provision(service, "deny")
    result = service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "deny"))
    assert result["authorization_status"] == AUTH_STATUS_DENIED
    assert result["authorization_granted"] is False
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["delegation_authorization_contract"]["governance_decision"]["reason_codes"] == ["EMERGENCY_STOP_ACTIVE"]


def test_authorization_contract_binds_exact_route_and_governance_policy_decision(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "bindings")
    result = service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "bindings"))
    c = result["delegation_authorization_contract"]
    assert c["identity"]["route_decision_id"] == route["route_decision_id"]
    assert c["source_bindings"]["route_decision_sha256"] == route["canonical_sha256"]
    assert c["source_bindings"]["governance_binding_version"] == 1
    assert c["delegation_subject"]["selected_subsystem"] == route["selected_subsystem"]
    assert c["delegation_subject"]["selected_capability"] == route["selected_capability"]
    assert c["governance_decision"]["policy_decision_id"] == result["policy_decision_id"]
    assert c["semantics"]["pre_delegation_revalidation_required"] is True


def test_exact_replay_is_idempotent_and_does_not_requery_governance_or_duplicate_event(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "replay")
    req = auth_request(service, mission_id, active, route, "replay")
    first = service.authorize_task_delegation(mission_id, req)
    event_count = service.get_mission_events(mission_id)["event_count"]
    second = service.authorize_task_delegation(mission_id, req)
    assert second["idempotent_replay"] is True
    assert second["delegation_authorization_id"] == first["delegation_authorization_id"]
    assert gov.evaluate_calls == 1
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_lost_external_response_is_recovered_by_operation_correlation_without_duplicate_query(tmp_path):
    gov = FakeGovernanceClient(); gov.fail_evaluate_after_commit_once = True
    service, _ = make_service(tmp_path / "m.db", gov)
    mission_id, active, route = provision(service, "recover")
    req = auth_request(service, mission_id, active, route, "recover")
    with pytest.raises(MissionGovernanceUnavailable):
        service.authorize_task_delegation(mission_id, req)
    assert gov.evaluate_calls == 1
    recovered = service.authorize_task_delegation(mission_id, req)
    assert recovered["authorization_granted"] is True
    assert gov.evaluate_calls == 1


def test_missing_governance_binding_fails_closed_before_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "no-binding", bind_governance=False)
    with pytest.raises(MissionGovernanceBindingNotFound):
        service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "no-binding"))
    assert gov.evaluate_calls == 0


def test_unbound_cti_delegation_is_durably_denied(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "deny-non-recon", allow_cti=False)
    assert route["selected_subsystem"] == "CTI"
    result = service.authorize_task_delegation(
        mission_id, auth_request(service, mission_id, active, route, "deny-non-recon")
    )
    assert result["authorization_status"] == AUTH_STATUS_DENIED
    assert result["authorization_granted"] is False
    assert gov.evaluate_calls == 1


def test_unscoped_cti_fake_allow_is_rejected_even_with_matching_attestation(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "fake-allow", allow_cti=False)
    original = gov.evaluate_authorization

    def forged_allow(payload):
        response = original(payload)
        response["decision"] = "ALLOW"
        response["constraints"]["allowed_capabilities"] = ["CTI:cti.read.context"]
        response["constraints"]["delegation_scope"]["delegation_authorized"] = True
        return response

    gov.evaluate_authorization = forged_allow
    with pytest.raises(MissionGovernanceProtocolError, match="authoritative scope"):
        service.authorize_task_delegation(
            mission_id, auth_request(service, mission_id, active, route, "fake-allow")
        )
    assert service.get_task_delegation_authorization_history(mission_id)["authorization_count"] == 0


def test_one_immutable_authorization_per_route_decision(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "single")
    service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "single"))
    with pytest.raises(MissionDelegationAuthorizationConflict, match="already has an immutable"):
        service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "single-2"))


def test_idempotency_key_reuse_with_different_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "idem")
    req = auth_request(service, mission_id, active, route, "idem")
    service.authorize_task_delegation(mission_id, req)
    changed = deepcopy(req); changed["reason"] = "different"
    with pytest.raises(MissionDelegationAuthorizationConflict, match="idempotency_key"):
        service.authorize_task_delegation(mission_id, changed)


@pytest.mark.parametrize("field,value", [
    ("selected_subsystem", "CTI"), ("selected_capability", "cti.read.context"),
    ("authorization_granted", True), ("decision", "ALLOW"), ("endpoint", "http://x"),
    ("resource_assignment", {"worker":"x"}), ("delegation", True), ("dispatch", True),
    ("execution", True), ("target_action", "scan"),
])
def test_request_rejects_caller_supplied_authority_selection_or_execution_fields(tmp_path, field, value):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, active, route = provision(service, f"forbid-{field}")
    req = auth_request(service, mission_id, active, route, f"forbid-{field}")
    req[field] = value
    with pytest.raises(MissionValidationError, match="unsupported delegation authorization field"):
        service.authorize_task_delegation(mission_id, req)


@pytest.mark.parametrize("field,value", [
    ("expected_version_sha256", "0"*64), ("expected_state_version", 999999),
    ("expected_active_plan_version_record_id", "pver-stale"), ("expected_active_plan_version", 99),
    ("expected_active_plan_sha256", "1"*64), ("expected_route_decision_sha256", "2"*64),
])
def test_stale_source_bindings_fail_closed(tmp_path, field, value):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, active, route = provision(service, f"stale-{field}")
    req = auth_request(service, mission_id, active, route, f"stale-{field}"); req[field] = value
    with pytest.raises(MissionConcurrencyConflict):
        service.authorize_task_delegation(mission_id, req)


def test_planned_task_mismatch_is_guard_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "task-mismatch")
    req = auth_request(service, mission_id, active, route, "task-mismatch", planned_task_id="ptask-other")
    with pytest.raises(MissionDelegationAuthorizationGuardRejected, match="planned_task_id"):
        service.authorize_task_delegation(mission_id, req)


def test_lineage_event_records_authorization_but_no_delegation_dispatch_or_execution(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route = provision(service, "event")
    result = service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "event"))
    matches = [e for e in service.get_mission_events(mission_id)["events"] if e["event_type"] == "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED"]
    assert len(matches) == 1
    event = matches[0]
    assert event["causation_id"] == result["delegation_authorization_id"]
    assert event["payload"]["route_decision_id"] == route["route_decision_id"]
    assert event["payload"]["authorization_granted"] is True
    assert event["payload"]["delegation_performed"] is False
    assert event["payload"]["dispatch_performed"] is False
    assert event["payload"]["execution_authorized"] is False


def test_repository_manifest_includes_delegation_authorization_store_and_restart_reconstructs(tmp_path):
    path = tmp_path / "m.db"
    service, gov = make_service(path)
    mission_id, active, route = provision(service, "restart")
    result = service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "restart"))
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_delegation_authorizations"] == 1
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(path)), governance_client=gov)
    restored = restarted.get_task_delegation_authorization(mission_id, result["delegation_authorization_id"])
    assert restored["canonical_sha256"] == result["canonical_sha256"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_tampering_persisted_authorization_contract_is_detected(tmp_path):
    path = tmp_path / "m.db"
    service, _ = make_service(path)
    mission_id, active, route = provision(service, "tamper")
    service.authorize_task_delegation(mission_id, auth_request(service, mission_id, active, route, "tamper"))
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT delegation_authorization_id, canonical_json FROM mission_delegation_authorizations WHERE mission_id=?", (mission_id,)).fetchone()
        bad = row[1].replace('"authorization_granted":true', '"authorization_granted":false')
        conn.execute("UPDATE mission_delegation_authorizations SET canonical_json=? WHERE delegation_authorization_id=?", (bad, row[0]))
        conn.commit()
    with pytest.raises((RuntimeError, MissionRepositoryIntegrityError)):
        service.get_mission_repository(mission_id)

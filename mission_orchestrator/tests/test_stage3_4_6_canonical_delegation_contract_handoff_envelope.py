from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.delegation_handoff import (
    DELEGATION_CONTRACT_SCHEMA_VERSION,
    HANDOFF_ENVELOPE_SCHEMA_VERSION,
    DELEGATION_MODE,
    HANDOFF_MODE,
    DELEGATION_ID_PREFIX,
    HANDOFF_ENVELOPE_ID_PREFIX,
    canonical_delegation_definition,
    verify_delegation_contract,
    verify_handoff_envelope,
    verify_pre_delegation_revalidation,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskDelegationConflict,
    MissionTaskDelegationGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_1_4_governance_authorization_binding import FakeGovernanceClient, scope_payload
from tests.test_stage3_4_5_governance_bound_delegation_authorization import (
    auth_request,
    make_service,
    provision,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def test_pre_delegation_revalidation_requires_current_gss_allow_and_execution_denial():
    result = {
        "revalidation_id": "greval-123",
        "status": "VALID",
        "valid": True,
        "delegation_authorized": True,
        "execution_authorized": False,
        "decision_hash": "a" * 64,
        "authority": "aptsGSS",
        "authority_component": "GOV-PLANE",
    }
    assert verify_pre_delegation_revalidation(result, policy_decision_hash="a" * 64)
    assert not verify_pre_delegation_revalidation(
        {**result, "execution_authorized": True}, policy_decision_hash="a" * 64
    )
    assert not verify_pre_delegation_revalidation(
        {**result, "delegation_authorized": False}, policy_decision_hash="a" * 64
    )


def provision_authorized(service, key: str):
    mission_id, active, route = provision(service, key)
    authorization = service.authorize_task_delegation(
        mission_id, auth_request(service, mission_id, active, route, key)
    )
    return mission_id, active, route, authorization


def delegation_request(service, mission_id, active, route, authorization, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage346-deleg-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_delegation_authorization_id": authorization["delegation_authorization_id"],
        "expected_delegation_authorization_sha256": authorization["canonical_sha256"],
        "planned_task_id": route["planned_task_id"],
        "delegated_by": "stage3.4.6-pytest",
        "reason": "Materialize canonical logical delegation and immutable handoff envelope only",
        "metadata": {"stage": "3.4.6", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage346_and_preserves_dispatch_execution_boundary(tmp_path):
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
    assert health["delegation_contract_schema_version"] == DELEGATION_CONTRACT_SCHEMA_VERSION
    assert health["delegation_handoff_envelope_schema_version"] == HANDOFF_ENVELOPE_SCHEMA_VERSION
    assert health["task_delegation_mode"] == DELEGATION_MODE
    assert health["task_delegation_handoff_mode"] == HANDOFF_MODE
    assert health["task_delegation_delegation_performed"] is True
    assert health["task_delegation_handoff_envelope_materialized"] is True
    assert health["task_delegation_handoff_transmitted"] is False
    assert health["task_delegation_handoff_acknowledged"] is False
    assert health["task_delegation_ownership_accepted"] is False
    assert health["task_delegation_dispatch_performed"] is False
    assert health["task_delegation_execution_authorized"] is False
    assert health["task_delegation_governance_query_performed"] is False
    assert health["task_delegation_pre_dispatch_governance_revalidation_required"] is True
    assert health["task_delegation_persistence_store"] == "mission_task_delegations"
    assert "mission_task_delegations" in REPOSITORY_STORES


def test_definition_declares_exact_stage346_contract_and_handoff_semantics(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision(service, "definition", bind_governance=False)
    result = service.get_task_delegation_definition(mission_id)
    definition = result["task_delegation_definition"]
    assert definition == canonical_delegation_definition()
    assert definition["requires_stage345_authorized_decision"] is True
    assert definition["recipient_derived_from_stage344_route"] is True
    assert definition["work_context_derived_from_planned_task_and_scope"] is True
    assert definition["delegation_performed"] is True
    assert definition["handoff_envelope_materialized"] is True
    assert definition["handoff_transmitted"] is False
    assert definition["ownership_accepted"] is False
    assert definition["dispatch_performed"] is False
    assert definition["execution_authorized"] is False


def test_authorized_route_materializes_immutable_delegation_and_handoff_without_dispatch(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "happy")
    calls_before = gov.evaluate_calls
    result = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "happy")
    )
    assert result["delegation_id"].startswith(DELEGATION_ID_PREFIX)
    assert result["handoff_envelope_id"].startswith(HANDOFF_ENVELOPE_ID_PREFIX)
    assert result["delegation_performed"] is True
    assert result["handoff_envelope_materialized"] is True
    assert result["handoff_transmitted"] is False
    assert result["handoff_acknowledged"] is False
    assert result["ownership_accepted"] is False
    assert result["dispatch_performed"] is False
    assert result["execution_authorized"] is False
    assert result["target_actuation"] is False
    assert result["governance_query_performed"] is False
    assert gov.evaluate_calls == calls_before == 1
    assert verify_delegation_contract(result["delegation_contract"])
    assert verify_handoff_envelope(result["handoff_envelope"])


def test_handoff_envelope_carries_canonical_recipient_work_scope_authority_and_provenance(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "envelope")
    result = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "envelope")
    )
    handoff = result["handoff_envelope"]
    recipient = handoff["recipient"]
    work = handoff["work_context"]
    authority = handoff["authority_context"]
    planned = service.get_planned_task(mission_id, route["planned_task_id"])["planned_task"]
    scope = service.get_mission_scope_contract(mission_id)["contract"]

    assert recipient["subsystem_id"] == route["selected_subsystem"]
    assert recipient["capability_id"] == route["selected_capability"]
    assert recipient["logical_recipient_only"] is True
    assert recipient["runtime_endpoint"] is None
    assert work["objective"] == planned["specification"]["objective"]
    assert work["preconditions"] == planned["specification"]["preconditions"]
    assert work["expected_outputs"] == planned["specification"]["expected_outputs"]
    assert work["completion_criteria"] == planned["specification"]["success_criteria"]
    assert work["evidence_requirements"] == planned["specification"]["evidence_requirements"]
    assert work["scope"] == scope["scope"]
    assert work["rules_of_engagement"] == scope["roe"]
    assert work["constraints"] == scope["constraints"]
    assert authority["delegation_authorization_id"] == authorization["delegation_authorization_id"]
    assert authority["delegation_authorization_sha256"] == authorization["canonical_sha256"]
    assert authority["authorization_status"] == "AUTHORIZED"
    assert authority["authorization_granted"] is True
    assert authority["execution_authorized"] is False
    assert authority["target_action_authorized"] is False
    assert authority["pre_dispatch_governance_revalidation_required"] is True
    revalidation = authority["pre_delegation_revalidation"]
    assert revalidation["valid"] is True
    assert revalidation["delegation_authorized"] is True
    assert revalidation["execution_authorized"] is False
    assert revalidation["authority"] == "aptsGSS"
    assert authority["pre_delegation_revalidation_sha256"]


def test_delegation_contract_binds_exact_authorization_route_plan_task_scope_and_governance(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "bindings")
    result = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "bindings")
    )
    contract = result["delegation_contract"]
    source = contract["source_bindings"]
    scope = service.repository.get_current_scope_contract(mission_id)
    governance = service.repository.get_current_governance_binding(mission_id)
    planned = service.repository.get_planned_task(mission_id, route["planned_task_id"])
    assert source["active_plan_sha256"] == active["canonical_sha256"]
    assert source["planned_task_sha256"] == planned["canonical_sha256"]
    assert source["mission_scope_sha256"] == scope["canonical_sha256"]
    assert source["governance_binding_sha256"] == governance["canonical_sha256"]
    assert source["route_decision_sha256"] == route["canonical_sha256"]
    assert source["delegation_authorization_sha256"] == authorization["canonical_sha256"]
    assert contract["semantics"]["authorization_reused_as_execution_grant"] is False
    assert contract["semantics"]["version_vector_extension_performed"] is False


def test_exact_replay_is_idempotent_without_duplicate_event_or_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "replay")
    req = delegation_request(service, mission_id, active, route, authorization, "replay")
    first = service.create_task_delegation(mission_id, req)
    event_count = service.get_mission_events(mission_id)["event_count"]
    calls = gov.evaluate_calls
    second = service.create_task_delegation(mission_id, req)
    assert second["idempotent_replay"] is True
    assert second["delegation_id"] == first["delegation_id"]
    assert second["handoff_envelope_id"] == first["handoff_envelope_id"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    assert gov.evaluate_calls == calls


def test_handoff_is_rejected_if_current_gss_delegation_revalidation_fails(tmp_path):
    gov = FakeGovernanceClient()
    service, _ = make_service(tmp_path / "m.db", gov)
    mission_id, active, route, authorization = provision_authorized(service, "revalidation-deny")
    gov.fail_revalidation = True
    with pytest.raises(MissionTaskDelegationGuardRejected, match="current GSS delegation authorization"):
        service.create_task_delegation(
            mission_id,
            delegation_request(service, mission_id, active, route, authorization, "revalidation-deny"),
        )
    assert service.get_task_delegation_history(mission_id)["delegation_count"] == 0
    assert gov.revalidation_calls == 1


def test_idempotency_key_reuse_with_different_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "idem")
    req = delegation_request(service, mission_id, active, route, authorization, "idem")
    service.create_task_delegation(mission_id, req)
    changed = deepcopy(req)
    changed["reason"] = "different"
    with pytest.raises(MissionTaskDelegationConflict, match="idempotency_key"):
        service.create_task_delegation(mission_id, changed)


@pytest.mark.parametrize("field,value", [
    ("recipient", {"subsystem_id": "CTI"}),
    ("selected_subsystem", "CTI"),
    ("selected_capability", "cti.read.context"),
    ("objective", {"goal": "caller-controlled"}),
    ("scope", {"targets": []}),
    ("constraints", {"max_actions": 999}),
    ("expected_outputs", []),
    ("completion_criteria", []),
    ("evidence_requirements", []),
    ("endpoint", "http://attacker.invalid"),
    ("handoff", {"transmit": True}),
    ("dispatch", True),
    ("ownership", True),
    ("execution", True),
    ("target_action", "scan"),
])
def test_request_rejects_caller_supplied_derived_handoff_or_execution_fields(tmp_path, field, value):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, active, route, authorization = provision_authorized(service, f"forbid-{field}")
    req = delegation_request(service, mission_id, active, route, authorization, f"forbid-{field}")
    req[field] = value
    with pytest.raises(MissionValidationError, match="unsupported delegation field"):
        service.create_task_delegation(mission_id, req)


def test_denied_stage345_authorization_cannot_materialize_delegation(tmp_path):
    gov = FakeGovernanceClient()
    gov.emergency_stop = True
    service, _ = make_service(tmp_path / "m.db", gov)
    mission_id, active, route = provision(service, "denied")
    authorization = service.authorize_task_delegation(
        mission_id, auth_request(service, mission_id, active, route, "denied")
    )
    assert authorization["authorization_granted"] is False
    with pytest.raises(MissionTaskDelegationGuardRejected, match="AUTHORIZED"):
        service.create_task_delegation(
            mission_id, delegation_request(service, mission_id, active, route, authorization, "denied")
        )


@pytest.mark.parametrize("field", [
    "expected_version_sha256",
    "expected_active_plan_sha256",
    "expected_delegation_authorization_sha256",
])
def test_stale_hash_expectations_fail_closed(tmp_path, field):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, active, route, authorization = provision_authorized(service, f"stale-{field}")
    req = delegation_request(service, mission_id, active, route, authorization, f"stale-{field}")
    req[field] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.create_task_delegation(mission_id, req)


def test_stage345_authorization_stale_after_scope_revision_fails_closed(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "scope-revision")
    service.put_mission_scope_contract(mission_id, scope_payload("scope-346-revision", expected=1, max_actions=7))
    req = delegation_request(service, mission_id, active, route, authorization, "scope-revision")
    with pytest.raises(MissionTaskDelegationGuardRejected, match="stale"):
        service.create_task_delegation(mission_id, req)


def test_one_immutable_delegation_per_authorization(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "single")
    service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "single")
    )
    with pytest.raises(MissionTaskDelegationConflict, match="already has an immutable"):
        service.create_task_delegation(
            mission_id, delegation_request(service, mission_id, active, route, authorization, "single-second")
        )


def test_event_lineage_records_materialization_not_transmission_dispatch_or_execution(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "event")
    result = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "event")
    )
    event = service.repository.get_mission_event_by_causation(
        mission_id, "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED", result["delegation_id"]
    )
    assert event is not None
    payload = event["payload"]
    assert payload["handoff_envelope_id"] == result["handoff_envelope_id"]
    assert payload["delegation_performed"] is True
    assert payload["handoff_envelope_materialized"] is True
    assert payload["handoff_transmitted"] is False
    assert payload["handoff_acknowledged"] is False
    assert payload["ownership_accepted"] is False
    assert payload["dispatch_performed"] is False
    assert payload["execution_authorized"] is False
    assert payload["target_action_dispatch_enabled"] is False


def test_restart_reads_same_delegation_and_handoff_from_durable_repository(tmp_path):
    db = tmp_path / "m.db"
    service, gov = make_service(db)
    mission_id, active, route, authorization = provision_authorized(service, "restart")
    created = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "restart")
    )
    restarted, _ = make_service(db, gov)
    loaded = restarted.get_task_delegation(mission_id, created["delegation_id"])
    assert loaded["canonical_sha256"] == created["canonical_sha256"]
    assert loaded["handoff_envelope_sha256"] == created["handoff_envelope_sha256"]
    assert loaded["delegation_contract"] == created["delegation_contract"]


def test_repository_manifest_includes_stage346_store_and_event_with_integrity_pass(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization = provision_authorized(service, "repository")
    service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "repository")
    )
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_task_delegations"] == 1
    assert len(repo["persistence_manifest"]["task_delegation_store"]["delegations"]) == 1
    checks = {x["check"]: x["status"] for x in repo["integrity_checks"]}
    assert checks["canonical_task_delegation_handoff_store"] == "PASS"


def test_tampered_delegation_contract_is_detected_by_repository_integrity(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, active, route, authorization = provision_authorized(service, "tamper")
    created = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, "tamper")
    )
    contract = deepcopy(created["delegation_contract"])
    contract["delegation"]["delegated_to_capability"] = "tampered.capability"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_task_delegations SET canonical_json=? WHERE delegation_id=?",
            (json.dumps(contract, sort_keys=True, separators=(",", ":")), created["delegation_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError, match="canonical_task_delegation_handoff_store"):
        service.get_mission_repository(mission_id)

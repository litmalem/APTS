from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.delegation_recovery import (
    ACTION_FALLBACK_NEXT_ELIGIBLE,
    ACTION_FREEZE_OWNERSHIP_CONFLICT,
    ACTION_REASSIGN_NEXT_ELIGIBLE,
    ACTION_RETRY_CURRENT_OWNER,
    CONFLICT_STATUS_FROZEN,
    MAX_RETRY_ATTEMPTS,
    OUTCOME_CONFLICT_FROZEN,
    OUTCOME_NO_ALTERNATE,
    OUTCOME_RETRY_ADMITTED,
    OUTCOME_RETRY_BUDGET_EXHAUSTED,
    RECOVERY_CONTROL_ID_PREFIX,
    RECOVERY_CONTROL_MODE,
    RECOVERY_CONTROL_SCHEMA_VERSION,
    canonical_recovery_control_definition,
    select_next_eligible_candidate,
    verify_recovery_control_contract,
)
from mission_orchestrator.errors import (
    MissionDelegationRecoveryControlConflict,
    MissionDelegationRecoveryControlGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.task_route_selection import TASK_ROUTE_SELECTION_HASH_DOMAIN, sha256_hex as route_sha256
from tests.test_stage3_4_7_delegation_delivery_acknowledgement_ownership import (
    delivery_request,
    make_service,
    provision_delegated,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision_owned(service, key: str):
    mission_id, active, route, authorization, delegation = provision_delegated(service, key)
    delivery = service.deliver_task_delegation(
        mission_id,
        delivery_request(service, mission_id, active, delegation, key),
    )
    return mission_id, active, route, authorization, delegation, delivery


def recovery_request(
    service,
    mission_id: str,
    active: dict,
    route: dict,
    delegation: dict,
    delivery: dict,
    key: str,
    *,
    action: str = ACTION_RETRY_CURRENT_OWNER,
    expected_control_count: int | None = None,
    **overrides,
):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    if expected_control_count is None:
        expected_control_count = len(
            service.repository.list_delegation_recovery_controls(mission_id, delivery["delivery_receipt_id"])
        )
    body = {
        "idempotency_key": f"stage348-control-{key}-{expected_control_count}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_route_decision_id": route["route_decision_id"],
        "expected_route_decision_sha256": route["canonical_sha256"],
        "expected_delegation_id": delegation["delegation_id"],
        "expected_delegation_sha256": delegation["canonical_sha256"],
        "expected_delivery_receipt_id": delivery["delivery_receipt_id"],
        "expected_delivery_receipt_sha256": delivery["canonical_sha256"],
        "expected_control_count": expected_control_count,
        "control_action": action,
        "requested_by": "APTS-MO01",
        "reason": "Stage 3.4.8 control-plane recovery decision only; no dispatch or execution",
        "metadata": {"stage": "3.4.8", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage348_and_preserves_no_dispatch_execution_boundary(tmp_path):
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
    assert health["delegation_recovery_control_schema_version"] == RECOVERY_CONTROL_SCHEMA_VERSION
    assert health["delegation_recovery_control_mode"] == RECOVERY_CONTROL_MODE
    assert health["delegation_recovery_control_max_retry_attempts"] == MAX_RETRY_ATTEMPTS == 3
    assert health["delegation_recovery_control_requires_stage347_ownership_receipt"] is True
    assert health["delegation_recovery_control_ownership_transfer_performed"] is False
    assert health["delegation_recovery_control_governance_query_performed"] is False
    assert health["delegation_recovery_control_dispatch_performed"] is False
    assert health["delegation_recovery_control_execution_authorized"] is False
    assert health["delegation_recovery_control_pre_dispatch_governance_revalidation_required"] is True
    assert health["delegation_recovery_control_database_migration_level"] == 25
    assert health["delegation_recovery_control_persistence_store"] == "mission_delegation_recovery_controls"
    assert "mission_delegation_recovery_controls" in REPOSITORY_STORES


def test_definition_declares_retry_fallback_reassignment_conflict_control_semantics(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision_owned(service, "definition348")
    result = service.get_delegation_recovery_control_definition(mission_id)
    definition = result["delegation_recovery_control_definition"]
    assert definition == canonical_recovery_control_definition()
    assert definition["max_retry_attempts"] == 3
    assert definition["requires_stage347_ownership_receipt"] is True
    assert definition["fallback_candidate_source"] == "IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES_ONLY"
    assert definition["caller_selected_fallback_forbidden"] is True
    assert definition["retry_retains_current_owner"] is True
    assert definition["fallback_or_reassignment_transfers_ownership"] is False
    assert definition["fallback_or_reassignment_requires_fresh_route_and_governance_control"] is True
    assert definition["conflict_freeze_is_fail_closed"] is True
    assert definition["dispatch_performed"] is False
    assert definition["execution_authorized"] is False


def test_retry_current_owner_materializes_immutable_control_without_dispatch_or_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "retry348")
    calls_before = gov.evaluate_calls
    result = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "retry348"),
    )
    assert result["recovery_control_id"].startswith(RECOVERY_CONTROL_ID_PREFIX)
    assert result["control_sequence"] == 1
    assert result["control_action"] == ACTION_RETRY_CURRENT_OWNER
    assert result["control_outcome"] == OUTCOME_RETRY_ADMITTED
    assert result["retry_ordinal"] == 1
    assert result["retry_admitted"] is True
    assert result["current_owner_subsystem"] == delivery["recipient_subsystem"]
    assert result["ownership_transfer_performed"] is False
    assert result["governance_query_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["execution_authorized"] is False
    assert result["target_actuation"] is False
    assert gov.evaluate_calls == calls_before == 1
    assert verify_recovery_control_contract(result["recovery_control"])


def test_retry_chain_binds_predecessor_and_enforces_three_attempt_budget(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "budget348")
    created = []
    for ordinal in range(1, 4):
        req = recovery_request(
            service, mission_id, active, route, delegation, delivery, f"budget348-{ordinal}"
        )
        result = service.control_task_delegation_recovery(mission_id, req)
        created.append(result)
        assert result["retry_ordinal"] == ordinal
        assert result["control_outcome"] == OUTCOME_RETRY_ADMITTED
        assert result["retry_admitted"] is True
        source = result["recovery_control"]["source_bindings"]
        if ordinal == 1:
            assert source["previous_recovery_control_id"] is None
        else:
            assert source["previous_recovery_control_id"] == created[-2]["recovery_control_id"]
            assert source["previous_recovery_control_sha256"] == created[-2]["canonical_sha256"]

    exhausted = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "budget348-4"),
    )
    assert exhausted["control_sequence"] == 4
    assert exhausted["retry_ordinal"] == 4
    assert exhausted["control_outcome"] == OUTCOME_RETRY_BUDGET_EXHAUSTED
    assert exhausted["retry_admitted"] is False
    with pytest.raises(MissionDelegationRecoveryControlGuardRejected, match="retry budget is exhausted"):
        service.control_task_delegation_recovery(
            mission_id,
            recovery_request(service, mission_id, active, route, delegation, delivery, "budget348-5"),
        )


@pytest.mark.parametrize("action", [ACTION_FALLBACK_NEXT_ELIGIBLE, ACTION_REASSIGN_NEXT_ELIGIBLE])
def test_fallback_and_reassignment_fail_closed_when_stage344_has_no_alternate_candidate(tmp_path, action):
    service, _ = make_service(tmp_path / f"{action}.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, action.lower())
    result = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(
            service, mission_id, active, route, delegation, delivery, action.lower(), action=action
        ),
    )
    assert result["control_action"] == action
    assert result["control_outcome"] == OUTCOME_NO_ALTERNATE
    assert result["candidate"] is None
    assert result["proposed_subsystem"] is None
    assert result["ownership_transition_pending"] is False
    assert result["ownership_transfer_performed"] is False
    assert result["route_reselection_required"] is False
    assert result["fresh_governance_authorization_required"] is False
    assert result["dispatch_performed"] is False


def test_next_fallback_candidate_is_deterministically_derived_from_immutable_stage344_ranking(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    _, _, route, _, _, _ = provision_owned(service, "candidate348")
    contract = deepcopy(route["route_selection_contract"])
    first = deepcopy(contract["route_decision"]["ranked_candidates"][0])
    second = deepcopy(first)
    second.update(
        {
            "rank": 2,
            "candidate_index": int(first["candidate_index"]) + 1,
            "subsystem_id": "PENTEST",
            "capability_id": "pentest.execute.assessment",
            "capability_version": 1,
        }
    )
    second["selection_key"] = {
        "candidate_index": second["candidate_index"],
        "subsystem_id": second["subsystem_id"],
        "capability_id": second["capability_id"],
        "capability_version": second["capability_version"],
    }
    contract["route_decision"]["ranked_candidates"] = [first, second]
    contract["route_decision"]["eligible_candidate_count"] = 2
    contract["route_decision"]["ranked_candidate_count"] = 2
    core = {k: v for k, v in contract.items() if k != "integrity"}
    contract["integrity"]["canonical_sha256"] = route_sha256(
        {"hash_domain": TASK_ROUTE_SELECTION_HASH_DOMAIN, "core": core}
    )
    candidate = select_next_eligible_candidate(
        contract,
        current_subsystem=first["subsystem_id"],
        current_capability=first["capability_id"],
        current_capability_version=first["capability_version"],
    )
    assert candidate == {
        "rank": 2,
        "candidate_index": second["candidate_index"],
        "subsystem_id": "PENTEST",
        "capability_id": "pentest.execute.assessment",
        "capability_version": 1,
        "side_effect_class": second.get("side_effect_class"),
        "source": "IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES",
        "runtime_endpoint_resolved": False,
        "runtime_health_probed": False,
    }


def test_conflict_freeze_is_immutable_fail_closed_and_blocks_follow_on_control(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "freeze348")
    frozen = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(
            service,
            mission_id,
            active,
            route,
            delegation,
            delivery,
            "freeze348",
            action=ACTION_FREEZE_OWNERSHIP_CONFLICT,
        ),
    )
    assert frozen["control_outcome"] == OUTCOME_CONFLICT_FROZEN
    assert frozen["conflict_status"] == CONFLICT_STATUS_FROZEN
    assert frozen["conflict_frozen"] is True
    assert frozen["ownership_transfer_performed"] is False
    with pytest.raises(MissionDelegationRecoveryControlGuardRejected, match="conflict-frozen"):
        service.control_task_delegation_recovery(
            mission_id,
            recovery_request(service, mission_id, active, route, delegation, delivery, "after-freeze348"),
        )


def test_expected_control_count_is_compare_and_swap_conflict_guard(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "cas348")
    service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "cas348-first"),
    )
    stale = recovery_request(
        service,
        mission_id,
        active,
        route,
        delegation,
        delivery,
        "cas348-stale",
        expected_control_count=0,
    )
    with pytest.raises(MissionDelegationRecoveryControlConflict, match="expected_control_count"):
        service.control_task_delegation_recovery(mission_id, stale)


def test_exact_replay_is_idempotent_without_duplicate_event_or_control(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "replay348")
    req = recovery_request(service, mission_id, active, route, delegation, delivery, "replay348")
    first = service.control_task_delegation_recovery(mission_id, req)
    event_count = service.get_mission_events(mission_id)["event_count"]
    calls = gov.evaluate_calls
    second = service.control_task_delegation_recovery(mission_id, req)
    assert second["idempotent_replay"] is True
    assert second["recovery_control_id"] == first["recovery_control_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    assert len(service.repository.list_delegation_recovery_controls(mission_id)) == 1
    assert gov.evaluate_calls == calls


def test_idempotency_key_reuse_with_changed_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "idem348")
    req = recovery_request(service, mission_id, active, route, delegation, delivery, "idem348")
    service.control_task_delegation_recovery(mission_id, req)
    changed = deepcopy(req)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionDelegationRecoveryControlConflict, match="idempotency_key"):
        service.control_task_delegation_recovery(mission_id, changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_subsystem", "PENTEST"),
        ("fallback_candidate", {"subsystem_id": "PENTEST"}),
        ("reassignment_candidate", {"subsystem_id": "PENTEST"}),
        ("recipient", {"subsystem_id": "PENTEST"}),
        ("runtime_endpoint", "http://attacker.invalid"),
        ("health", {"status": "UP"}),
        ("resource_assignment", {"worker": "w1"}),
        ("governance_decision", "ALLOW"),
        ("dispatch", True),
        ("execution_authorized", True),
        ("target_action", "scan"),
    ],
)
def test_request_rejects_caller_supplied_candidate_runtime_authority_or_execution_fields(tmp_path, field, value):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, f"forbid-{field}")
    req = recovery_request(service, mission_id, active, route, delegation, delivery, f"forbid-{field}")
    req[field] = value
    with pytest.raises(MissionValidationError, match="unsupported delegation recovery-control field"):
        service.control_task_delegation_recovery(mission_id, req)


def test_non_owner_non_orchestrator_requester_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "requester348")
    req = recovery_request(
        service,
        mission_id,
        active,
        route,
        delegation,
        delivery,
        "requester348",
        requested_by="UNRELATED-SUBSYSTEM",
    )
    with pytest.raises(MissionDelegationRecoveryControlGuardRejected, match="requested_by"):
        service.control_task_delegation_recovery(mission_id, req)


def test_stage346_delegation_and_stage347_ownership_receipt_remain_immutable(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "immutable348")
    before_delegation = deepcopy(service.repository.get_task_delegation(mission_id, delegation["delegation_id"]))
    before_delivery = deepcopy(service.repository.get_delegation_delivery(mission_id, delivery["delivery_receipt_id"]))
    service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "immutable348"),
    )
    after_delegation = service.repository.get_task_delegation(mission_id, delegation["delegation_id"])
    after_delivery = service.repository.get_delegation_delivery(mission_id, delivery["delivery_receipt_id"])
    assert after_delegation["canonical_sha256"] == before_delegation["canonical_sha256"]
    assert after_delegation["delegation_contract"] == before_delegation["delegation_contract"]
    assert after_delivery["canonical_sha256"] == before_delivery["canonical_sha256"]
    assert after_delivery["delivery_receipt_contract"] == before_delivery["delivery_receipt_contract"]


def test_recovery_event_records_control_decision_without_dispatch_or_execution(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "event348")
    result = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "event348"),
    )
    event = service.repository.get_mission_event_by_causation(
        mission_id,
        "MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED",
        result["recovery_control_id"],
    )
    assert event is not None
    payload = event["payload"]
    assert payload["control_action"] == ACTION_RETRY_CURRENT_OWNER
    assert payload["control_outcome"] == OUTCOME_RETRY_ADMITTED
    assert payload["ownership_transfer_performed"] is False
    assert payload["governance_query_performed"] is False
    assert payload["dispatch_performed"] is False
    assert payload["execution_authorized"] is False
    assert payload["target_action_dispatch_enabled"] is False
    assert payload["target_actuation"] is False


def test_restart_reads_same_recovery_control_from_durable_repository(tmp_path):
    db = tmp_path / "m.db"
    service, gov = make_service(db)
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "restart348")
    created = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "restart348"),
    )
    restarted, _ = make_service(db, gov)
    loaded = restarted.get_delegation_recovery_control(mission_id, created["recovery_control_id"])
    assert loaded["canonical_sha256"] == created["canonical_sha256"]
    assert loaded["recovery_control"] == created["recovery_control"]


def test_repository_manifest_includes_stage348_store_and_integrity_pass(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "repository348")
    service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "repository348"),
    )
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_delegation_recovery_controls"] == 1
    assert len(repo["persistence_manifest"]["delegation_recovery_control_store"]["controls"]) == 1
    checks = {x["check"]: x["status"] for x in repo["integrity_checks"]}
    assert checks["delegation_retry_fallback_reassignment_conflict_control_store"] == "PASS"


def test_repository_integrity_detects_stage348_control_corruption(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "corrupt348")
    created = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, "corrupt348"),
    )
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT canonical_json FROM mission_delegation_recovery_controls WHERE recovery_control_id=?",
            (created["recovery_control_id"],),
        ).fetchone()
        contract = json.loads(row[0])
        contract["recovery_control"]["control_outcome"] = "CORRUPTED"
        conn.execute(
            "UPDATE mission_delegation_recovery_controls SET canonical_json=? WHERE recovery_control_id=?",
            (json.dumps(contract, separators=(",", ":"), sort_keys=True), created["recovery_control_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(
        MissionRepositoryIntegrityError,
        match="delegation_retry_fallback_reassignment_conflict_control_store",
    ):
        service.get_mission_repository(mission_id)

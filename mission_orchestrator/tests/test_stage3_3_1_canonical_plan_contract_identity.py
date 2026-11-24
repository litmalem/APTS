from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionPlanContractConflict,
    MissionPlanContractGuardRejected,
    MissionPlanContractNotFound,
    MissionValidationError,
)
from mission_orchestrator.mission_plan import (
    PLAN_CONTRACT_HASH_DOMAIN,
    PLAN_CONTRACT_MODE,
    PLAN_CONTRACT_SCHEMA_VERSION,
    PLAN_LIFECYCLE_STATE_REQUIRED,
    PLAN_TASK_GRAPH_STATUS_INITIAL,
    verify_plan_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService


class NoExternalClient:
    base_url = "disabled://stage3.3.1"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.3.1 must remain local-only: unexpected external call {name}")


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": f"stage331-mission-{key}",
        "source_system": "STAGE331_PYTEST",
        "created_by": "stage3.3.1-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage331-lab"},
        "success_criteria": [
            {"metric": "canonical_plan_identity", "expected": True},
            {"metric": "no_authority_expansion", "expected": True},
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-stage331-{key}",
        "pip_version": "15",
        "metadata": {"environment": "LAB", "stage": "3.3.1"},
    }


def create_mission(service: CanonicalMissionService, key: str) -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "command_id": f"lc-331-{token}",
        "idempotency_key": f"idem-lc-331-{token}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.3.1-pytest",
        "reason_code": f"STAGE331_{command}",
        "reason": f"Stage 3.3.1 prerequisite command {command}",
        "evidence_refs": [f"evidence:stage331:{token}"],
        "metadata": {"stage": "3.3.1", "token": token},
    }


def execute(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    return service.execute_mission_lifecycle_command(
        mission_id, lifecycle_request(service, mission_id, command, token)
    )


def activate_planning(service: CanonicalMissionService, mission_id: str, token: str) -> None:
    execute(service, mission_id, "BIND_PIP", f"bind-{token}")
    execute(service, mission_id, "START_PLANNING", f"planning-{token}")


def plan_request(service: CanonicalMissionService, mission_id: str, key: str = "plan") -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "idempotency_key": f"stage331-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.1-pytest",
        "reason": "Register immutable canonical plan identity",
        "metadata": {"stage": "3.3.1", "key": key},
    }


def scope_payload(key: str = "scope") -> dict:
    return {
        "expected_contract_version": 0,
        "idempotency_key": f"stage331-{key}",
        "actor": "stage3.3.1-pytest",
        "scope": {
            "targets": [
                {"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}
            ],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
            "domains": ["lab.example.test"],
            "services": [{"name": "https", "protocol": "TCP", "port": 443, "target_ref": "lab.example.test"}],
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": ["VULNERABILITY_VALIDATION"],
        },
        "constraints": {
            "max_actions": 10,
            "max_duration": 1200,
            "risk_threshold": "LOW",
            "resource_budget": {"max_network_requests": 100},
            "data_handling_policy": {"classification": "INTERNAL"},
        },
        "reason": "Stage 3.3.1 scope binding test",
        "metadata": {"stage": "3.3.1"},
    }


def test_health_opens_stage331_and_preserves_authority_execution_boundaries(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][19:30] == [
        "stage3.2.10-lifecycle-acceptance-regression-gate",
        "stage3.3.1-canonical-plan-contract-identity",
        "stage3.3.2-planner-input-snapshot-context-binding",
        "stage3.3.3-canonical-task-decomposition-contract",
        "stage3.3.4-task-dependency-graph-structural-validation",
        "stage3.3.5-planner-invocation-plan-generation",
        "stage3.3.6-plan-validation-feasibility-gate",
        "stage3.3.7-plan-versioning-replanning-supersession",
        "stage3.3.8-task-readiness-scheduling-projection",
        "stage3.3.9-planning-event-lineage-replay-recovery",
        "stage3.3.10-planning-acceptance-regression-gate",
    ]
    assert health["mission_plan_contract_schema_version"] == PLAN_CONTRACT_SCHEMA_VERSION
    assert health["mission_plan_contract_mode"] == PLAN_CONTRACT_MODE
    assert health["mission_plan_contract_creation_state_required"] == PLAN_LIFECYCLE_STATE_REQUIRED
    assert health["mission_plan_contract_requires_stage3_2_4_planning_activation_lineage"] is True
    assert health["mission_plan_contract_planner_invocation_performed"] is False
    assert health["mission_plan_contract_task_decomposition_performed"] is False
    assert health["mission_plan_contract_plan_revision_performed"] is False
    assert health["mission_plan_contract_plan_is_authorization"] is False
    assert health["mission_plan_contract_task_is_dispatch"] is False
    assert health["mission_plan_contract_readiness_is_permission"] is False
    assert health["mission_plan_contract_planner_is_governance"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False
    assert health["mission_repository_migration_level"] == 53
    assert REPOSITORY_MIGRATION_LEVEL == 53


def test_plan_contract_definition_is_discoverable_before_registration(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "definition")
    result = service.get_mission_plan_contract_definition(mission_id)
    contract = result["plan_contract_definition"]
    assert result["plan_registered"] is False
    assert contract["schema_version"] == PLAN_CONTRACT_SCHEMA_VERSION
    assert contract["creation_state_required"] == "PLANNING"
    assert contract["task_graph_status_at_stage3_3_1"] == PLAN_TASK_GRAPH_STATUS_INITIAL
    assert contract["plan_is_authorization"] is False
    assert contract["task_is_dispatch"] is False
    assert contract["readiness_is_permission"] is False
    assert contract["planner_is_governance"] is False


def test_plan_registration_fails_closed_before_planning(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "too-early")
    with pytest.raises(MissionPlanContractGuardRejected):
        service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "too-early"))
    with pytest.raises(MissionPlanContractNotFound):
        service.get_mission_plan_contract(mission_id)


def test_canonical_plan_identity_is_immutable_hashed_and_bound_to_planning_lineage(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "canonical")
    activate_planning(service, mission_id, "canonical")
    before = service.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["mission_plan_version"] == 0

    result = service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "canonical"))
    contract = result["plan_contract"]
    assert result["idempotent_replay"] is False
    assert result["plan_id"].startswith("mplan-")
    assert result["plan_version"] == 1
    assert contract["identity"]["mission_id"] == mission_id
    assert contract["identity"]["plan_id"] == result["plan_id"]
    assert contract["mission_binding"]["mission_id"] == mission_id
    assert contract["planning_activation_binding"]["state"] == "PLANNING"
    assert contract["planning_activation_binding"]["planning_transition_to_state"] == "PLANNING"
    assert contract["task_graph"] == {
        "status": "NOT_MATERIALIZED",
        "task_count": 0,
        "dependency_edge_count": 0,
        "tasks": [],
        "dependency_edges": [],
    }
    assert contract["semantics"]["planner_invocation_performed"] is False
    assert contract["semantics"]["task_decomposition_performed"] is False
    assert contract["semantics"]["plan_is_authorization"] is False
    assert contract["semantics"]["task_is_dispatch"] is False
    assert contract["integrity"]["hash_domain"] == PLAN_CONTRACT_HASH_DOMAIN
    assert verify_plan_contract(contract)

    after = service.get_mission_version_vector(mission_id)
    assert after["version_vector"]["versions"]["mission_plan_version"] == 1
    assert after["version_sha256"] != before["version_sha256"]


def test_exact_retry_is_idempotent_and_does_not_duplicate_plan_or_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "replay")
    activate_planning(service, mission_id, "replay")
    request = plan_request(service, mission_id, "replay")
    first = service.create_mission_plan_contract(mission_id, request)
    events_after_first = service.get_mission_events(mission_id)["event_count"]
    second = service.create_mission_plan_contract(mission_id, request)
    events_after_second = service.get_mission_events(mission_id)["event_count"]
    assert second["idempotent_replay"] is True
    assert second["plan_id"] == first["plan_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert events_after_second == events_after_first
    assert service.repository.get_repository_record_counts(mission_id)["mission_plans"] == 1


def test_idempotency_conflict_and_second_plan_identity_are_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "conflict")
    activate_planning(service, mission_id, "conflict")
    request = plan_request(service, mission_id, "same-key")
    service.create_mission_plan_contract(mission_id, request)

    changed = dict(request)
    changed["metadata"] = {"changed": True}
    with pytest.raises(MissionPlanContractConflict):
        service.create_mission_plan_contract(mission_id, changed)

    fresh = dict(request)
    fresh["idempotency_key"] = "stage331-second-identity"
    with pytest.raises(MissionPlanContractConflict):
        service.create_mission_plan_contract(mission_id, fresh)


def test_stale_version_and_state_tokens_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "stale")
    activate_planning(service, mission_id, "stale")
    request = plan_request(service, mission_id, "stale")

    bad_vector = dict(request)
    bad_vector["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.create_mission_plan_contract(mission_id, bad_vector)

    bad_state = dict(request)
    bad_state["expected_state_version"] = int(request["expected_state_version"]) - 1
    with pytest.raises(MissionConcurrencyConflict):
        service.create_mission_plan_contract(mission_id, bad_state)


def test_legacy_direct_planning_transition_cannot_bypass_stage324_lineage(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "legacy")
    # Legacy API is preserved, but Stage 3.3.1 requires the stronger Stage-3.2.4 lineage.
    state = service.get_mission_state(mission_id)["mission_state"]
    service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": "PIP_BOUND",
            "actor": "legacy-test",
            "reason_code": "LEGACY_PIP",
            "reason": "legacy transition",
            "evidence_refs": [],
            "metadata": {"legacy": True},
        },
    )
    state = service.get_mission_state(mission_id)["mission_state"]
    service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": "PLANNING",
            "actor": "legacy-test",
            "reason_code": "LEGACY_PLANNING",
            "reason": "legacy transition",
            "evidence_refs": [],
            "metadata": {"legacy": True},
        },
    )
    with pytest.raises(MissionPlanContractGuardRejected):
        service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "legacy"))


def test_plan_binds_exact_local_scope_snapshot_when_present(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "scope")
    scope = service.put_mission_scope_contract(mission_id, scope_payload("scope"))
    activate_planning(service, mission_id, "scope")
    result = service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "scope"))
    bound = result["plan_contract"]["mission_binding"]["scope"]
    assert bound == {
        "binding_status": "BOUND",
        "mission_scope_contract_id": scope["mission_scope_contract_id"],
        "scope_version": 1,
        "scope_snapshot_id": scope["snapshot_id"],
        "scope_sha256": scope["canonical_sha256"],
    }


def test_plan_registration_adds_canonical_event_and_repository_integrity_projection(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "repo")
    activate_planning(service, mission_id, "repo")
    plan = service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "repo"))

    events = service.get_mission_events(mission_id)
    plan_events = [x for x in events["events"] if x["event_type"] == "MISSION_PLAN_CONTRACT_REGISTERED"]
    assert len(plan_events) == 1
    assert plan_events[0]["causation_id"] == plan["plan_id"]
    assert plan_events[0]["plan_version"] == "1"

    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert "mission_plans" in repo["repository"]["stores"]
    assert repo["record_counts"]["mission_plans"] == 1
    assert repo["persistence_manifest"]["mission_plan_store"]["plan_id"] == plan["plan_id"]
    assert any(x["check"] == "canonical_plan_contract_store" and x["status"] == "PASS" for x in repo["integrity_checks"])


def test_restart_reconstructs_plan_without_external_reads(tmp_path):
    db = tmp_path / "missions.db"
    first = make_service(db)
    mission_id = create_mission(first, "restart")
    activate_planning(first, mission_id, "restart")
    created = first.create_mission_plan_contract(mission_id, plan_request(first, mission_id, "restart"))

    restarted = make_service(db)
    restored = restarted.get_mission_plan_contract(mission_id)
    repo = restarted.get_mission_repository(mission_id)
    assert restored["plan_id"] == created["plan_id"]
    assert restored["canonical_sha256"] == created["canonical_sha256"]
    assert verify_plan_contract(restored["plan_contract"])
    assert repo["integrity_status"] == "PASS"


def test_stage331_rejects_task_or_planner_fields_in_contract_request(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "unknown-fields")
    activate_planning(service, mission_id, "unknown-fields")
    request = plan_request(service, mission_id, "unknown-fields")
    request["tasks"] = [{"task_id": "not-yet-allowed"}]
    with pytest.raises(MissionValidationError):
        service.create_mission_plan_contract(mission_id, request)


def test_migration_009_declares_plan_store_and_authority_boundary():
    sql = Path("migrations/009_stage3_3_1_canonical_plan_contract_identity.sql").read_text().lower()
    assert "create table if not exists mission_plans" in sql
    assert "unique key uq_mission_plan_mission" in sql
    assert "plan_id" in sql and "plan_version" in sql and "canonical_sha256" in sql
    assert "source_state_version" in sql and "source_transition_id" in sql
    assert "plan != authorization" in sql
    assert "planner != governance" in sql
    assert "does not invoke a planner" in sql
    assert "    9," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53

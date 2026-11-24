from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionGovernanceBindingConflict,
    MissionSubsystemUnavailable,
    MissionTaskConflict,
    MissionTaskRoutingFailClosed,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_routing import verify_task_contract


class FakeGovernance:
    base_url = "fake://governance"

    def __init__(self):
        self.scopes = []
        self.create_calls = 0

    def create_scope_contract(self, payload):
        self.create_calls += 1
        scope = {
            "scope_contract_id": f"scope-{self.create_calls}",
            "mission_id": payload["mission_id"],
            "name": payload.get("name"),
            "status": "ACTIVE",
            "policy_set_id": payload["policy_set_id"],
            "version": 1,
            "contract_hash": ("a" if self.create_calls == 1 else "b") * 64,
            "targets": list(payload.get("targets") or []),
            "sources": list(payload.get("sources") or []),
            "action_constraints": list(payload.get("action_constraints") or []),
            "metadata": dict(payload.get("metadata") or {}),
        }
        self.scopes.append(scope)
        return dict(scope)

    def get_scope_contract(self, scope_contract_id):
        return dict(next(item for item in self.scopes if item["scope_contract_id"] == scope_contract_id))

    def mission_correlation_snapshot(self, mission_id):
        return {
            "mission_id": mission_id,
            "scope_contracts": [dict(x) for x in self.scopes if x["mission_id"] == mission_id],
            "authorization_requests": [],
            "policy_decisions": [],
            "events": [],
        }


class FakeCti:
    base_url = "fake://cti"

    def __init__(self):
        self.start_calls = 0
        self.last_payload = None
        self.mission = {"status": "NOT_FOUND"}
        self.fail_after_commit_once = False
        self.fail_without_commit = False

    def get_mission(self, mission_id):
        return dict(self.mission)

    def start_mission(self, payload):
        self.start_calls += 1
        self.last_payload = dict(payload)
        if self.fail_without_commit:
            raise MissionSubsystemUnavailable("simulated CTI outage")
        self.mission = {
            "mission_id": payload["mission_id"],
            "status": "RUNNING",
            "state_version": 1,
            "plan_version": 1,
        }
        if self.fail_after_commit_once:
            self.fail_after_commit_once = False
            raise MissionSubsystemUnavailable("simulated response loss after CTI commit")
        return {"status": "accepted", "mission_id": payload["mission_id"], "plan_id": "plan-315"}


def mission_payload(key="mission-315", required=None):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab"},
        "success_criteria": [{"metric": "done", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": required if required is not None else ["CTI"],
        "metadata": {"environment": "LAB"},
    }


def scope_payload(key="scope-315", expected=0):
    return {
        "expected_contract_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": [],
            "domains": [],
            "services": [],
        },
        "roe": {
            "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "allowed_time_window": {"start_at": "2026-09-01T00:00:00Z", "end_at": "2030-09-03T00:00:00Z"},
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": [],
        },
        "constraints": {
            "max_actions": 20,
            "max_duration": 1800,
            "risk_threshold": "MODERATE",
            "resource_budget": {"max_network_requests": 500},
            "data_handling_policy": {"classification": "INTERNAL", "retention_days": 7, "export_allowed": False},
        },
        "reason": "pytest scope",
        "metadata": {"environment": "LAB"},
    }


def binding_payload(key="bind-315", expected=0):
    return {
        "expected_binding_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "policy_set_id": "default-policy",
        "name": "Stage 3.1.5 route binding",
        "capabilities": [
            {
                "capability_id": "orchestrator.route.cti",
                "subject_component": "CTI-A01",
                "action_class": "INTERNAL_REASONING",
                "action_name": "START_CTI_MISSION",
                "authorization_mode": "NOT_REQUIRED_INTERNAL",
                "resource_types": [],
                "max_risk_level": "LOW",
                "requires_human_approval": False,
            },
            {
                "capability_id": "pentest.recon",
                "subject_component": "CTI-A02",
                "action_class": "TARGET_RECON",
                "action_name": "recon",
                "authorization_mode": "REQUIRED",
                "resource_types": ["IP"],
                "max_risk_level": "MODERATE",
                "requires_human_approval": False,
            },
        ],
        "reason": "bind internal route plus target capability",
        "metadata": {"test": True},
    }


def task_payload(key="task-315", capability="orchestrator.route.cti", task_input=None):
    return {
        "idempotency_key": key,
        "capability_id": capability,
        "task_input": task_input or {"auto_acquire_cti": False, "scan": {"host": "127.0.0.1"}},
        "requested_by": "pytest",
        "reason": "route CTI subsystem mission",
        "metadata": {"test": True},
    }


def make_service(tmp_path: Path, *, cti=None):
    gov = FakeGovernance()
    cti = cti or FakeCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=gov, cti_client=cti), gov, cti


def transition(svc, mission_id, expected, to_state):
    return svc.transition_mission_state(
        mission_id,
        {
            "expected_state_version": expected,
            "to_state": to_state,
            "actor": "pytest",
            "reason_code": f"MOVE_TO_{to_state}",
            "metadata": {},
        },
    )


def provision(tmp_path: Path, *, cti=None, required=None):
    svc, gov, cti = make_service(tmp_path, cti=cti)
    mission_id = svc.create_mission(mission_payload(required=required))["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload())
    svc.put_mission_governance_binding(mission_id, binding_payload())
    transition(svc, mission_id, 1, "PIP_BOUND")
    transition(svc, mission_id, 2, "PLANNING")
    return svc, gov, cti, mission_id


def test_create_governed_task_derives_cti_route_from_bound_subject(tmp_path):
    svc, _, _, mission_id = provision(tmp_path)
    result = svc.create_governed_routing_task(mission_id, task_payload())
    assert result["task_status"] == "READY"
    assert result["destination_subsystem"] == "CTI"
    contract = result["task_contract"]
    assert verify_task_contract(contract)
    assert contract["capability"]["subject_component"] == "CTI-A01"
    assert contract["routing"]["dispatch_path"] == "/api/cti/missions/start"
    assert contract["semantics"]["target_action_dispatch"] is False
    assert contract["semantics"]["target_actuation"] is False


def test_task_create_is_idempotent_and_conflicting_replay_rejected(tmp_path):
    svc, _, _, mission_id = provision(tmp_path)
    first = svc.create_governed_routing_task(mission_id, task_payload("same-task"))
    second = svc.create_governed_routing_task(mission_id, task_payload("same-task"))
    assert second["idempotent_replay"] is True
    assert second["task_id"] == first["task_id"]
    changed = task_payload("same-task", task_input={"auto_acquire_cti": True})
    with pytest.raises(MissionTaskConflict):
        svc.create_governed_routing_task(mission_id, changed)


def test_only_one_subsystem_mission_route_per_global_mission(tmp_path):
    svc, _, _, mission_id = provision(tmp_path)
    svc.create_governed_routing_task(mission_id, task_payload("task-a"))
    with pytest.raises(MissionTaskConflict, match="already has"):
        svc.create_governed_routing_task(mission_id, task_payload("task-b"))


def test_required_target_capability_cannot_be_used_as_subsystem_mission_route(tmp_path):
    svc, _, _, mission_id = provision(tmp_path)
    with pytest.raises(MissionTaskRoutingFailClosed, match="NOT_REQUIRED_INTERNAL"):
        svc.create_governed_routing_task(mission_id, task_payload(capability="pentest.recon"))


def test_route_must_be_declared_in_immutable_required_subsystems(tmp_path):
    svc, _, _, mission_id = provision(tmp_path, required=[])
    with pytest.raises(MissionTaskRoutingFailClosed, match="not declared"):
        svc.create_governed_routing_task(mission_id, task_payload())


def test_task_creation_requires_planning_running_or_replanning_state(tmp_path):
    svc, _, _ = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload())
    svc.put_mission_governance_binding(mission_id, binding_payload())
    with pytest.raises(MissionTaskRoutingFailClosed, match="CREATED"):
        svc.create_governed_routing_task(mission_id, task_payload())


def test_scope_revision_after_binding_blocks_new_route_task(tmp_path):
    svc, _, _, mission_id = provision(tmp_path)
    svc.put_mission_scope_contract(mission_id, scope_payload("scope-v2", expected=1))
    with pytest.raises(MissionGovernanceBindingConflict, match="stale"):
        svc.create_governed_routing_task(mission_id, task_payload())


def test_dispatch_requires_running_or_replanning_and_sends_exact_lineage(tmp_path):
    svc, _, cti, mission_id = provision(tmp_path)
    task = svc.create_governed_routing_task(mission_id, task_payload())
    with pytest.raises(MissionTaskRoutingFailClosed, match="requires canonical mission state"):
        svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    transition(svc, mission_id, 3, "RUNNING")
    result = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    assert result["task_status"] == "DISPATCHED"
    assert cti.start_calls == 1
    assert cti.last_payload["mission_id"] == mission_id
    assert cti.last_payload["global_task_id"] == task["task_id"]
    route_meta = cti.last_payload["mission_orchestrator_routing"]
    assert route_meta["task_contract_sha256"] == task["canonical_sha256"]
    assert route_meta["capability_id"] == "orchestrator.route.cti"


def test_dispatch_replay_does_not_start_second_cti_mission(tmp_path):
    svc, _, cti, mission_id = provision(tmp_path)
    task = svc.create_governed_routing_task(mission_id, task_payload())
    transition(svc, mission_id, 3, "RUNNING")
    first = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    second = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    assert first["task_status"] == "DISPATCHED"
    assert second["idempotent_replay"] is True
    assert cti.start_calls == 1


def test_dispatch_recovers_when_cti_commits_but_response_is_lost(tmp_path):
    cti = FakeCti()
    cti.fail_after_commit_once = True
    svc, _, cti, mission_id = provision(tmp_path, cti=cti)
    task = svc.create_governed_routing_task(mission_id, task_payload())
    transition(svc, mission_id, 3, "RUNNING")
    result = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    assert result["task_status"] == "DISPATCHED"
    assert result["recovered_after_response_loss"] is True
    assert cti.start_calls == 1
    assert result["dispatch_attempts"][-1]["recovered_after_response_loss"] is True


def test_dispatch_outage_fails_closed_and_keeps_task_ready_for_retry(tmp_path):
    cti = FakeCti()
    cti.fail_without_commit = True
    svc, _, _, mission_id = provision(tmp_path, cti=cti)
    task = svc.create_governed_routing_task(mission_id, task_payload())
    transition(svc, mission_id, 3, "RUNNING")
    with pytest.raises(MissionSubsystemUnavailable):
        svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    stored = svc.get_governed_routing_task(mission_id, task["task_id"])
    assert stored["task_status"] == "READY"
    assert stored["dispatch_attempts"][-1]["status"] == "RETRYABLE"


def test_read_only_routing_projection_recommends_cleanup_without_mutating_state(tmp_path):
    svc, _, cti, mission_id = provision(tmp_path)
    task = svc.create_governed_routing_task(mission_id, task_payload())
    transition(svc, mission_id, 3, "RUNNING")
    svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    cti.mission.update({"status": "COMPLETED", "state_version": 9, "plan_version": 2})
    before = svc.get_mission_state(mission_id)["mission_state"]
    projection = svc.get_routing_projection(mission_id)
    after = svc.get_mission_state(mission_id)["mission_state"]
    assert projection["routing_projection"] == "SUBSYSTEMS_COMPLETED"
    assert projection["recommended_canonical_state"] == "CLEANING_UP"
    assert projection["canonical_state_mutated"] is False
    assert before == after


def test_health_exposes_stage315_without_enabling_target_action_dispatch(tmp_path):
    svc, _, _ = make_service(tmp_path)
    health = svc.health()
    assert "stage3.1.5-governed-task-routing" in health["supported_controls"]
    assert "stage3.1.4-governance-authorization-binding-contract" in health["supported_controls"]
    assert health["governed_task_routing_mode"] == "BOUND_INTERNAL_CAPABILITY_DERIVED_DESTINATION_FAIL_CLOSED"
    assert health["subsystem_routing_dispatch_enabled"] is True
    assert health["supported_routing_subsystems"] == ["CTI"]
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False

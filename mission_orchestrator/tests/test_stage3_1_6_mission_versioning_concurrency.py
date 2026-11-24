from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionCommandConflict,
    MissionConcurrencyConflict,
    MissionSubsystemUnavailable,
    MissionVersionObservationUnavailable,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class FakeGovernance:
    base_url = "fake://governance"

    def __init__(self):
        self.scopes = []
        self.requests = []
        self.decisions = []
        self.events = []
        self.create_calls = 0
        self.evaluate_calls = 0

    @staticmethod
    def _hash(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def create_scope_contract(self, payload):
        self.create_calls += 1
        row = {
            "scope_contract_id": f"scope-316-{self.create_calls}",
            "mission_id": payload["mission_id"],
            "name": payload.get("name"),
            "status": "ACTIVE",
            "policy_set_id": payload["policy_set_id"],
            "version": 1,
            "targets": list(payload.get("targets") or []),
            "sources": list(payload.get("sources") or []),
            "action_constraints": list(payload.get("action_constraints") or []),
            "metadata": dict(payload.get("metadata") or {}),
        }
        row["contract_hash"] = self._hash(row)
        self.scopes.append(row)
        return dict(row)

    def get_scope_contract(self, scope_contract_id):
        return dict(next(x for x in self.scopes if x["scope_contract_id"] == scope_contract_id))

    def evaluate_authorization(self, payload):
        self.evaluate_calls += 1
        scope = self.get_scope_contract(payload["scope_contract_id"])
        request_id = f"greq-316-{self.evaluate_calls}"
        decision_id = f"gdec-316-{self.evaluate_calls}"
        request = {
            "request_id": request_id,
            "mission_id": payload["mission_id"],
            "scope_contract_id": payload["scope_contract_id"],
            "subject_component": payload["subject_component"],
            "action_class": payload["action_class"],
            "action_name": payload["action_name"],
            "resource_type": payload["resource_type"],
            "resource_value": payload["resource_value"],
            "context": dict(payload.get("context") or {}),
            "evidence_refs": list(payload.get("evidence_refs") or []),
            "requested_by": payload.get("requested_by"),
        }
        self.requests.append(request)
        decision = {
            "decision_id": decision_id,
            "request_id": request_id,
            "mission_id": payload["mission_id"],
            "decision": "ALLOW",
            "risk_score": 0.2,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "IP_MATCH"],
            "constraints": {},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": "2026-09-02T00:00:00Z",
            "valid_until": "2030-09-02T00:00:00Z",
            "policy_set_id": scope["policy_set_id"],
            "policy_version": 7,
            "scope_contract_id": scope["scope_contract_id"],
            "scope_version": scope["version"],
        }
        decision["decision_hash"] = self._hash(decision)
        decision["decision_status"] = "ACTIVE"
        event_id = f"gevent-316-{self.evaluate_calls}"
        self.decisions.append(dict(decision))
        self.events.append(
            {
                "event_id": event_id,
                "event_type": "POLICY_DECISION_ISSUED",
                "mission_id": payload["mission_id"],
                "payload": {**decision, "governance_event_id": event_id},
            }
        )
        return {**decision, "governance_event_id": event_id}

    def mission_correlation_snapshot(self, mission_id):
        return {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "scope_contracts": [dict(x) for x in self.scopes if x["mission_id"] == mission_id],
            "authorization_requests": [dict(x) for x in self.requests if x["mission_id"] == mission_id],
            "policy_decisions": [dict(x) for x in self.decisions if x["mission_id"] == mission_id],
            "events": [dict(x) for x in self.events if x["mission_id"] == mission_id],
            "audit_records": [],
        }


class FakeCti:
    base_url = "fake://cti"

    def __init__(self):
        self.start_calls = 0
        self.unavailable = False
        self.mission = {"status": "NOT_FOUND"}

    def start_mission(self, payload):
        self.start_calls += 1
        self.mission = {
            "mission_id": payload["mission_id"],
            "status": "RUNNING",
            "state_version": 1,
            "plan_version": 1,
        }
        return {"status": "accepted", "mission_id": payload["mission_id"], "plan_id": "plan-316"}

    def get_mission(self, mission_id):
        if self.unavailable:
            raise MissionSubsystemUnavailable("simulated CTI observation outage")
        return dict(self.mission)


def mission_payload(key="mission-316"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab"},
        "success_criteria": [{"metric": "done", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB"},
    }


def scope_payload(key="scope-316", expected=0):
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


def binding_payload(key="bind-316", expected=0):
    return {
        "expected_binding_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "policy_set_id": "default-policy",
        "name": "Stage 3.1.6 binding",
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
        "reason": "pytest binding",
        "metadata": {"test": True},
    }


def task_payload(key="task-316"):
    return {
        "idempotency_key": key,
        "capability_id": "orchestrator.route.cti",
        "task_input": {"auto_acquire_cti": False},
        "requested_by": "pytest",
        "reason": "route CTI",
        "metadata": {"test": True},
    }


def transition_payload(expected, to_state):
    return {
        "expected_state_version": expected,
        "to_state": to_state,
        "actor": "pytest",
        "reason_code": f"MOVE_TO_{to_state}",
        "metadata": {},
    }


def make_service(tmp_path: Path):
    gov = FakeGovernance()
    cti = FakeCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=gov, cti_client=cti), gov, cti


def command(token, command_id, operation, payload, idem=None):
    return {
        "command_id": command_id,
        "idempotency_key": idem or f"idem-{command_id}",
        "operation": operation,
        "expected_version_sha256": token,
        "payload": payload,
        "submitted_by": "pytest",
        "metadata": {"stage": "3.1.6"},
    }


def provision_routed(tmp_path: Path):
    svc, gov, cti = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload())
    svc.put_mission_governance_binding(mission_id, binding_payload())
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))
    task = svc.create_governed_routing_task(mission_id, task_payload())
    svc.transition_mission_state(mission_id, transition_payload(3, "RUNNING"))
    svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    return svc, gov, cti, mission_id, task


def test_version_vector_tracks_local_and_cti_version_domains(tmp_path):
    svc, _, _, mission_id, _ = provision_routed(tmp_path)
    result = svc.get_mission_version_vector(mission_id)
    vector = result["version_vector"]
    assert result["version_vector_complete"] is True
    assert len(result["version_sha256"]) == 64
    assert vector["versions"] == {
        "envelope_version": 1,
        "state_version": 4,
        "scope_contract_version": 1,
        "governance_binding_version": 1,
        "governance_scope_version": 1,
        "mission_plan_version": 0,
        "planner_input_snapshot_version": 0,
        "task_decomposition_version": 0,
        "task_dependency_graph_version": 0,
        "planner_generation_version": 0,
        "plan_validation_version": 0,
        "plan_versioning_version": 0,
        "task_readiness_projection_version": 0,
        "planning_recovery_version": 0,
        "policy_version": None,
        "cti_state_version": 1,
        "cti_plan_version": 1,
    }
    assert vector["subsystem_observations"]["cti_observation_status"] == "OBSERVED"
    assert vector["local_revisions"]["routing_task_count"] == 1


def test_guarded_state_transition_replays_duplicate_command_without_second_transition(tmp_path):
    svc, _, _ = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    body = command(token, "cmd-316-state-1", "STATE_TRANSITION", transition_payload(1, "PIP_BOUND"))

    first = svc.execute_mission_command(mission_id, body)
    replay = svc.execute_mission_command(mission_id, body)

    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert replay["result"]["transition"]["transition_id"] == first["result"]["transition"]["transition_id"]
    assert svc.get_mission_state(mission_id)["mission_state"]["state_version"] == 2
    assert svc.get_mission_state_history(mission_id)["transition_count"] == 1
    assert svc.get_mission_command_history(mission_id)["command_count"] == 1
    event_types = [e["event_type"] for e in svc.get_mission_events(mission_id)["events"]]
    assert event_types == [
        "MISSION_REGISTERED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_COMMAND_COMPLETED",
    ]
    assert event_types.count("MISSION_COMMAND_COMPLETED") == 1


def test_conflicting_duplicate_command_id_is_rejected(tmp_path):
    svc, _, _ = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    body = command(token, "cmd-316-conflict", "STATE_TRANSITION", transition_payload(1, "PIP_BOUND"))
    svc.execute_mission_command(mission_id, body)
    changed = command(token, "cmd-316-conflict", "STATE_TRANSITION", transition_payload(1, "PAUSED"))
    with pytest.raises(MissionCommandConflict):
        svc.execute_mission_command(mission_id, changed)


def test_stale_version_vector_rejects_write_without_mutation(tmp_path):
    svc, _, _ = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    stale = svc.get_mission_version_vector(mission_id)["version_sha256"]
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))

    body = command(stale, "cmd-316-stale", "STATE_TRANSITION", transition_payload(2, "PLANNING"))
    with pytest.raises(MissionConcurrencyConflict, match="does not match"):
        svc.execute_mission_command(mission_id, body)

    state = svc.get_mission_state(mission_id)["mission_state"]
    assert state["state"] == "PIP_BOUND"
    assert state["state_version"] == 2
    journal = svc.get_mission_command(mission_id, "cmd-316-stale")
    assert journal["command_status"] == "REJECTED_STALE"


def test_concurrent_guarded_transitions_from_same_version_only_one_wins(tmp_path):
    svc, _, _ = make_service(tmp_path)
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    barrier = threading.Barrier(3)
    results = []

    def worker(command_id, target):
        barrier.wait()
        try:
            value = svc.execute_mission_command(
                mission_id,
                command(token, command_id, "STATE_TRANSITION", transition_payload(1, target)),
            )
            results.append(("ok", value["result"]["mission_state"]["state"]))
        except Exception as exc:  # assertion below verifies the only allowed loser type
            results.append(("err", type(exc)))

    t1 = threading.Thread(target=worker, args=("cmd-316-race-a", "PIP_BOUND"))
    t2 = threading.Thread(target=worker, args=("cmd-316-race-b", "PAUSED"))
    t1.start(); t2.start(); barrier.wait(); t1.join(); t2.join()

    assert sum(1 for kind, _ in results if kind == "ok") == 1
    assert sum(1 for kind, value in results if kind == "err" and value is MissionConcurrencyConflict) == 1
    assert svc.get_mission_state(mission_id)["mission_state"]["state_version"] == 2
    assert svc.get_mission_state_history(mission_id)["transition_count"] == 1


def test_remote_cti_plan_drift_changes_vector_and_blocks_stale_command(tmp_path):
    svc, _, cti, mission_id, _ = provision_routed(tmp_path)
    stale = svc.get_mission_version_vector(mission_id)["version_sha256"]
    cti.mission["plan_version"] = 2
    fresh = svc.get_mission_version_vector(mission_id)
    assert fresh["version_vector"]["versions"]["cti_plan_version"] == 2
    assert fresh["version_sha256"] != stale

    body = command(stale, "cmd-316-plan-drift", "STATE_TRANSITION", transition_payload(4, "REPLANNING"))
    with pytest.raises(MissionConcurrencyConflict):
        svc.execute_mission_command(mission_id, body)
    assert svc.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


def test_incomplete_remote_version_observation_fails_guarded_mutation_closed(tmp_path):
    svc, _, cti, mission_id, _ = provision_routed(tmp_path)
    token = svc.get_mission_version_vector(mission_id)["version_sha256"]
    cti.unavailable = True
    degraded = svc.get_mission_version_vector(mission_id)
    assert degraded["version_vector_complete"] is False
    assert degraded["version_vector"]["subsystem_observations"]["cti_observation_status"] == "UNAVAILABLE_OR_INVALID"

    body = command(token, "cmd-316-observation-down", "STATE_TRANSITION", transition_payload(4, "REPLANNING"))
    with pytest.raises(MissionVersionObservationUnavailable):
        svc.execute_mission_command(mission_id, body)
    assert svc.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"
    assert svc.get_mission_command(mission_id, "cmd-316-observation-down")["command_status"] == "FAILED_OBSERVATION"
    with pytest.raises(MissionVersionObservationUnavailable):
        svc.execute_mission_command(mission_id, body)


def test_policy_version_enters_vector_after_authoritative_authorization(tmp_path):
    svc, _, _, mission_id, _ = provision_routed(tmp_path)
    before = svc.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["policy_version"] is None

    svc.authorize_mission_capability(
        mission_id,
        {
            "idempotency_key": "auth-316",
            "capability_id": "pentest.recon",
            "resource_type": "IP",
            "resource_value": "127.0.0.1",
            "context": {"environment": "LAB"},
            "evidence_refs": [],
            "requested_by": "pytest",
        },
    )
    after = svc.get_mission_version_vector(mission_id)
    assert after["version_vector"]["versions"]["policy_version"] == 7
    assert after["version_sha256"] != before["version_sha256"]


def test_health_declares_stage316_and_preserves_authority_boundary(tmp_path):
    svc, _, _ = make_service(tmp_path)
    health = svc.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert "stage3.1.6-mission-versioning-concurrency" in health["supported_controls"]
    assert health["mission_concurrency_mode"] == "OPTIMISTIC_VERSION_VECTOR_IDEMPOTENT_COMMAND_GATE"
    assert health["mission_command_gate_enabled"] is True
    assert health["mission_mutation_serialization_mode"] == "PROCESS_WIDE_REENTRANT_GUARD_PLUS_REPOSITORY_CAS"
    assert "cti_plan_version" in health["observed_version_domains"]
    assert "policy_version" in health["observed_version_domains"]
    assert "stage3.1.5-governed-task-routing" in health["supported_controls"]
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.acceptance_gate import (
    ACCEPTANCE_GATE_BASELINE,
    ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    ACCEPTANCE_GATE_MODE,
    ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_1_CONTROLS,
    acceptance_gate_contract,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionEventIntegrityError,
    MissionIllegalTransition,
    MissionRepositoryIntegrityError,
    MissionStateConflict,
    MissionTaskRoutingFailClosed,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService


class GateGovernance:
    base_url = "fake://governance-stage3110"

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
            "scope_contract_id": f"scope-3110-{self.create_calls}",
            "mission_id": payload["mission_id"],
            "name": payload.get("name"),
            "status": "ACTIVE",
            "policy_set_id": payload["policy_set_id"],
            "version": 1,
            "valid_from": payload.get("valid_from"),
            "valid_until": payload.get("valid_until"),
            "created_by": payload.get("created_by"),
            "approved_by": payload.get("approved_by"),
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
        request_id = f"greq-3110-{self.evaluate_calls}"
        decision_id = f"gdec-3110-{self.evaluate_calls}"
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
            "risk_score": 0.1,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "IP_MATCH"],
            "constraints": {},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": "2026-09-03T00:00:00Z",
            "valid_until": "2030-09-03T00:00:00Z",
            "policy_set_id": scope["policy_set_id"],
            "policy_version": 7,
            "scope_contract_id": scope["scope_contract_id"],
            "scope_version": scope["version"],
        }
        decision["decision_hash"] = self._hash(decision)
        decision["decision_status"] = "ACTIVE"
        event_id = f"gevent-3110-{self.evaluate_calls}"
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


class GateCti:
    base_url = "fake://cti-stage3110"

    def __init__(self):
        self.start_calls = 0
        self.get_calls = 0
        self.last_payload = None
        self.mission = {"status": "NOT_FOUND"}

    def start_mission(self, payload):
        self.start_calls += 1
        self.last_payload = dict(payload)
        self.mission = {
            "mission_id": payload["mission_id"],
            "status": "RUNNING",
            "state_version": 1,
            "plan_version": 1,
        }
        return {"status": "accepted", "mission_id": payload["mission_id"], "plan_id": "plan-3110"}

    def get_mission(self, mission_id):
        self.get_calls += 1
        return dict(self.mission)


class NoCallExternal:
    base_url = "fake://no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage-3.1.10 local reconstruction must not call external dependency: {name}")


def mission_payload(key="stage3110-mission"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE3110",
        "created_by": "stage3.1.10-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage3110-lab"},
        "success_criteria": [{"metric": "stage31_gate", "expected": True}],
        "budgets": {"time_seconds": 1800, "max_actions": 20, "risk_ceiling": "MODERATE"},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB", "stage": "3.1.10"},
    }


def scope_payload(key="stage3110-scope", expected=0):
    return {
        "expected_contract_version": expected,
        "idempotency_key": key,
        "actor": "stage3.1.10-pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
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
            "resource_budget": {"max_network_requests": 100, "max_parallel_targets": 1},
            "data_handling_policy": {"classification": "INTERNAL", "retention_days": 7, "export_allowed": False},
        },
        "reason": "Stage 3.1.10 acceptance/regression closure",
        "metadata": {"environment": "LAB", "stage": "3.1.10"},
    }


def binding_payload(key="stage3110-binding", expected=0):
    return {
        "expected_binding_version": expected,
        "idempotency_key": key,
        "actor": "stage3.1.10-pytest",
        "policy_set_id": "default-policy",
        "name": "Stage 3.1.10 closure binding",
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
        "reason": "Preserve external authorization and safe internal CTI routing",
        "metadata": {"stage": "3.1.10"},
    }


def auth_payload(key="stage3110-auth"):
    return {
        "idempotency_key": key,
        "capability_id": "pentest.recon",
        "resource_type": "IP",
        "resource_value": "127.0.0.1",
        "context": {"environment": "LAB"},
        "evidence_refs": ["evidence://stage3.1.10/regression"],
        "requested_by": "stage3.1.10-pytest",
        "metadata": {"stage": "3.1.10"},
    }


def task_payload(key="stage3110-task", capability="orchestrator.route.cti"):
    return {
        "idempotency_key": key,
        "capability_id": capability,
        "task_input": {"auto_acquire_cti": False, "metadata": {"stage": "3.1.10"}},
        "requested_by": "stage3.1.10-pytest",
        "reason": "Stage 3.1.10 governed CTI route",
        "metadata": {"stage": "3.1.10"},
    }


def transition_payload(expected, to_state):
    return {
        "expected_state_version": expected,
        "to_state": to_state,
        "actor": "stage3.1.10-pytest",
        "reason_code": f"STAGE3110_{to_state}",
        "reason": "Stage 3.1.10 regression transition",
        "evidence_refs": [],
        "metadata": {"stage": "3.1.10"},
    }


def command_payload(version_sha256, command_id, expected_state_version, to_state):
    return {
        "command_id": command_id,
        "idempotency_key": f"idem-{command_id}",
        "operation": "STATE_TRANSITION",
        "expected_version_sha256": version_sha256,
        "payload": transition_payload(expected_state_version, to_state),
        "submitted_by": "stage3.1.10-pytest",
        "metadata": {"stage": "3.1.10"},
    }


def make_service(db_path: Path, *, governance=None, cti=None):
    governance = governance or GateGovernance()
    cti = cti or GateCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(db_path))
    return CanonicalMissionService(repo, governance_client=governance, cti_client=cti), governance, cti


def provision_bound(svc, *, key_prefix="stage3110"):
    mission_id = svc.create_mission(mission_payload(f"{key_prefix}-mission"))["canonical_identity"]["mission_id"]
    svc.put_mission_scope_contract(mission_id, scope_payload(f"{key_prefix}-scope"))
    svc.put_mission_governance_binding(mission_id, binding_payload(f"{key_prefix}-binding"))
    return mission_id


def test_stage3110_health_declares_closure_gate_and_all_prior_controls(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    health = svc.health()

    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert "stage3.1.10-acceptance-regression-gate" in health["supported_controls"]
    assert health["supported_controls"][29] == "stage3.3.10-planning-acceptance-regression-gate"
    assert "stage3.2.10-lifecycle-acceptance-regression-gate" in health["supported_controls"]
    for control in REQUIRED_STAGE3_1_CONTROLS:
        assert control in health["supported_controls"]
    assert health["stage3_1_acceptance_gate_schema_version"] == ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_1_acceptance_gate_mode"] == ACCEPTANCE_GATE_MODE
    assert health["stage3_1_acceptance_gate_baseline"] == ACCEPTANCE_GATE_BASELINE
    assert health["stage3_1_acceptance_gate_runtime_change_mode"] == ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_1_acceptance_gate_database_change_mode"] == ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_1_acceptance_gate_expected_migration_level"] == 8
    assert health["stage3_1_acceptance_gate_declared_only"] is True
    assert health["stage3_1_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_1_acceptance_gate_external_execution_required"] is True
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_stage3110_valid_preflight_then_create_and_scope_commit_preserves_zero_side_effect_preflight(tmp_path):
    svc, gov, cti = make_service(tmp_path / "missions.db")
    draft = {"mission": mission_payload("preflight-3110"), "scope_contract": scope_payload("preflight-scope-3110")}

    report = svc.validate_canonical_mission(draft)
    assert report["valid"] is True
    assert [x["phase"] for x in report["checks"]] == ["SCHEMA", "SEMANTIC", "SCOPE", "CONSTRAINTS"]
    assert report["persistence_performed"] is False
    assert report["authority_query_performed"] is False
    assert report["planning_performed"] is False
    assert report["target_action_performed"] is False
    assert gov.create_calls == 0
    assert cti.start_calls == 0
    assert svc.repository.get_by_idempotency("PYTEST_STAGE3110", "preflight-3110") is None

    created = svc.create_mission(draft["mission"])
    assert created["idempotent_replay"] is False
    mission_id = created["canonical_identity"]["mission_id"]
    scope = svc.put_mission_scope_contract(mission_id, draft["scope_contract"])
    contract = svc.get_canonical_mission_contract(mission_id)
    assert scope["contract_version"] == 1
    assert contract["contract_complete"] is True
    assert contract["contract_status"] == "SCOPE_BOUND"
    assert contract["external_authority_query_performed"] is False


def test_stage3110_replays_create_scope_binding_and_task_without_duplicate_canonical_artifacts(tmp_path):
    svc, gov, _ = make_service(tmp_path / "missions.db")
    mission_body = mission_payload("replay-3110")
    created = svc.create_mission(mission_body)
    mission_id = created["canonical_identity"]["mission_id"]
    assert svc.create_mission(mission_body)["idempotent_replay"] is True

    scope_body = scope_payload("replay-scope-3110")
    first_scope = svc.put_mission_scope_contract(mission_id, scope_body)
    assert svc.put_mission_scope_contract(mission_id, scope_body)["idempotent_replay"] is True
    assert first_scope["contract_version"] == 1

    binding_body = binding_payload("replay-binding-3110")
    first_binding = svc.put_mission_governance_binding(mission_id, binding_body)
    second_binding = svc.put_mission_governance_binding(mission_id, binding_body)
    assert first_binding["idempotent_replay"] is False
    assert second_binding["idempotent_replay"] is True
    assert gov.create_calls == 1

    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))
    task_body = task_payload("replay-task-3110")
    first_task = svc.create_governed_routing_task(mission_id, task_body)
    second_task = svc.create_governed_routing_task(mission_id, task_body)
    assert second_task["idempotent_replay"] is True
    assert second_task["task_id"] == first_task["task_id"]

    events = svc.get_mission_events(mission_id)["events"]
    assert [event["event_type"] for event in events] == [
        "MISSION_REGISTERED",
        "MISSION_SCOPE_CONTRACT_COMMITTED",
        "MISSION_GOVERNANCE_BOUND",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_ROUTING_TASK_CREATED",
    ]


def test_stage3110_full_state_path_and_stale_guard_remain_fail_closed(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id = svc.create_mission(mission_payload("state-3110"))["canonical_identity"]["mission_id"]

    with pytest.raises(MissionIllegalTransition):
        svc.transition_mission_state(mission_id, transition_payload(1, "RUNNING"))
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    with pytest.raises(MissionStateConflict):
        svc.transition_mission_state(mission_id, transition_payload(1, "PLANNING"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))
    svc.transition_mission_state(mission_id, transition_payload(3, "RUNNING"))
    svc.transition_mission_state(mission_id, transition_payload(4, "REPLANNING"))
    svc.transition_mission_state(mission_id, transition_payload(5, "RUNNING"))
    svc.transition_mission_state(mission_id, transition_payload(6, "CLEANING_UP"))
    svc.transition_mission_state(mission_id, transition_payload(7, "COMPLETED"))

    state = svc.get_mission_state(mission_id)["mission_state"]
    assert state["state"] == "COMPLETED"
    assert state["state_version"] == 8
    assert svc.get_mission_state_history(mission_id)["transition_count"] == 7
    with pytest.raises(MissionIllegalTransition):
        svc.transition_mission_state(mission_id, transition_payload(8, "RUNNING"))


def test_stage3110_governance_authorization_stays_external_and_policy_version_enters_vector(tmp_path):
    svc, gov, _ = make_service(tmp_path / "missions.db")
    mission_id = provision_bound(svc, key_prefix="auth-3110")

    before = svc.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["policy_version"] is None
    auth = svc.authorize_mission_capability(mission_id, auth_payload("auth-decision-3110"))
    provenance = auth["authorization_binding"]["decision_provenance"]
    assert provenance["decision"] == "ALLOW"
    assert provenance["policy_version"] == 7
    assert provenance["authorization_authority"] == "aptsGSS"
    assert provenance["authorization_authority_component"] == "GOV-PLANE"
    assert gov.evaluate_calls == 1

    after = svc.get_mission_version_vector(mission_id)
    assert after["version_vector"]["versions"]["policy_version"] == 7
    assert after["version_sha256"] != before["version_sha256"]
    assert svc.health()["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert svc.health()["target_action_dispatch_enabled"] is False


def test_stage3110_internal_cti_routing_dispatches_once_while_target_capability_fails_closed(tmp_path):
    svc, _, cti = make_service(tmp_path / "missions.db")
    mission_id = provision_bound(svc, key_prefix="route-3110")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))

    task = svc.create_governed_routing_task(mission_id, task_payload("route-task-3110"))
    with pytest.raises(MissionTaskRoutingFailClosed):
        svc.create_governed_routing_task(mission_id, task_payload("target-route-3110", "pentest.recon"))
    svc.transition_mission_state(mission_id, transition_payload(3, "RUNNING"))

    first = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    replay = svc.dispatch_governed_routing_task(mission_id, task["task_id"])
    assert first["task_status"] == "DISPATCHED"
    assert replay["idempotent_replay"] is True
    assert cti.start_calls == 1
    assert cti.last_payload["mission_id"] == mission_id
    assert cti.last_payload["global_task_id"] == task["task_id"]
    assert task["task_contract"]["semantics"]["target_action_dispatch"] is False
    assert task["task_contract"]["semantics"]["target_actuation"] is False


def test_stage3110_command_gate_rejects_stale_vector_and_journals_rejection(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    mission_id = svc.create_mission(mission_payload("command-3110"))["canonical_identity"]["mission_id"]
    stale = svc.get_mission_version_vector(mission_id)["version_sha256"]
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))

    command = command_payload(stale, "cmd-stage3110-stale", 2, "PLANNING")
    with pytest.raises(MissionConcurrencyConflict):
        svc.execute_mission_command(mission_id, command)
    journal = svc.get_mission_command(mission_id, "cmd-stage3110-stale")
    assert journal["command_status"] == "REJECTED_STALE"
    state = svc.get_mission_state(mission_id)["mission_state"]
    assert state["state"] == "PIP_BOUND"
    assert state["state_version"] == 2


def test_stage3110_restart_reconstructs_repository_events_and_current_contract_without_external_reads(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = provision_bound(svc, key_prefix="restart-3110")
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    svc.transition_mission_state(mission_id, transition_payload(2, "PLANNING"))
    task = svc.create_governed_routing_task(mission_id, task_payload("restart-task-3110"))

    reconstructed = CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db_path)),
        governance_client=NoCallExternal(),
        cti_client=NoCallExternal(),
    )
    contract = reconstructed.get_canonical_mission_contract(mission_id)
    repository = reconstructed.get_mission_repository(mission_id)
    events = reconstructed.get_mission_events(mission_id)
    task_read = reconstructed.get_governed_routing_task(mission_id, task["task_id"])

    assert contract["contract_status"] == "SCOPE_BOUND"
    assert contract["mission_state"]["state"] == "PLANNING"
    assert repository["integrity_status"] == "PASS"
    assert repository["record_counts"]["mission_events"] == events["event_count"]
    assert events["integrity_status"] == "PASS"
    assert task_read["canonical_sha256"] == task["canonical_sha256"]


def test_stage3110_event_and_repository_integrity_fail_closed_after_tamper(tmp_path):
    db_path = tmp_path / "missions.db"
    svc, _, _ = make_service(db_path)
    mission_id = svc.create_mission(mission_payload("tamper-3110"))["canonical_identity"]["mission_id"]
    svc.transition_mission_state(mission_id, transition_payload(1, "PIP_BOUND"))
    event = svc.get_mission_events(mission_id)["events"][-1]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM mission_events WHERE event_id=?", (event["event_id"],)).fetchone()
        payload = json.loads(row[0])
        payload["to_state"] = "TAMPERED_BY_STAGE3110_TEST"
        conn.execute(
            "UPDATE mission_events SET payload_json=? WHERE event_id=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), event["event_id"]),
        )
        conn.commit()

    with pytest.raises(MissionEventIntegrityError):
        svc.get_mission_events(mission_id)
    with pytest.raises(MissionRepositoryIntegrityError):
        svc.get_mission_repository(mission_id)


def test_stage3110_closure_contract_requires_external_gate_and_no_new_database_migration():
    contract = acceptance_gate_contract()
    assert contract == {
        "schema_version": ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": ACCEPTANCE_GATE_MODE,
        "baseline": ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_1_CONTROLS),
        "required_gates": list(REQUIRED_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
    }
    assert ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 8
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migration_names = sorted(path.name for path in Path("migrations").glob("*.sql"))
    assert len(migration_names) == 53
    assert migration_names[7].startswith("008_stage3_1_9_")
    assert migration_names[8:] == [
        "009_stage3_3_1_canonical_plan_contract_identity.sql",
        "010_stage3_3_2_planner_input_snapshot_context_binding.sql",
        "011_stage3_3_3_canonical_task_decomposition_contract.sql",
        "012_stage3_3_4_task_dependency_graph_structural_validation.sql",
        "013_stage3_3_5_planner_invocation_plan_generation.sql",
        "014_stage3_3_6_plan_validation_feasibility_gate.sql",
        "015_stage3_3_7_plan_versioning_replanning_supersession.sql",
        "016_stage3_3_8_task_readiness_scheduling_projection.sql",
        "017_stage3_3_9_planning_event_lineage_replay_recovery.sql",
        "018_stage3_4_1_canonical_subsystem_registry_capability_contract.sql",
        "019_stage3_4_2_task_routing_intent_candidate_resolution.sql",
        "020_stage3_4_3_routing_eligibility_compatibility_gate.sql",
        "021_stage3_4_4_deterministic_route_selection_decision_record.sql",
        "022_stage3_4_5_governance_bound_delegation_authorization.sql",
        "023_stage3_4_6_canonical_delegation_contract_handoff_envelope.sql",
        "024_stage3_4_7_delegation_delivery_acknowledgement_ownership.sql",
        "025_stage3_4_8_retry_fallback_reassignment_conflict_control.sql",
        "026_stage3_4_9_routing_delegation_event_lineage_replay_recovery.sql",
        "027_stage3_5_1_canonical_execution_dispatch_contract_identity.sql",
        "028_stage3_5_2_dispatch_eligibility_execution_preconditions.sql",
        "029_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.sql",
        "030_stage3_5_4_idempotent_dispatch_execution_attempt_identity.sql",
        "031_stage3_5_5_dispatch_delivery_execution_acknowledgement.sql",
        "032_stage3_5_6_running_execution_state_heartbeat_projection.sql",
        "033_stage3_5_7_execution_result_evidence_artifact_capture.sql",
        "034_stage3_5_8_timeout_cancellation_abort_failure_propagation.sql",
        "035_stage3_5_9_execution_event_lineage_replay_recovery.sql",
        "036_stage3_6_1_canonical_task_outcome_contract_identity.sql",
        "037_stage3_6_2_task_terminality_completion_eligibility.sql",
        "038_stage3_6_3_evidence_binding_verification.sql",
        "039_stage3_6_4_dependency_aware_task_completion.sql",
        "040_stage3_6_5_mission_outcome_aggregation.sql",
        "041_stage3_6_6_mission_success_criteria_evaluation.sql",
        "042_stage3_6_7_completion_readiness_blockers.sql",
        "043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql",
        "044_stage3_6_9_outcome_lineage_replay_recovery.sql",
        "045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql",
        "046_stage3_7_2_adaptation_trigger_detection_classification.sql",
        "047_stage3_7_3_replan_eligibility_governance_gate.sql",
        "048_stage3_7_4_canonical_replan_snapshot_context_binding.sql",
        "049_stage3_7_5_deterministic_replan_candidate_generation.sql",
        "050_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.sql",
        "051_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.sql",
        "052_stage3_7_8_atomic_replan_commit_supersession_handoff.sql",
        "053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql",
    ]

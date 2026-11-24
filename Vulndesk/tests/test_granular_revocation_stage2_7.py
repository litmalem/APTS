from __future__ import annotations

import os
import sys
import types
from copy import deepcopy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_PATH = os.path.join(ROOT, "cti_services")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

if "cpe_dictionary_services" not in sys.modules:
    cpe_module = types.ModuleType("cpe_dictionary_services")

    class _FakeCpeDictionaryService:
        def match_technologies(self, *args, **kwargs):
            return []

    cpe_module.CpeDictionaryService = _FakeCpeDictionaryService
    sys.modules["cpe_dictionary_services"] = cpe_module

from cti_services.cti_subsystem_orchestrator import (
    CtiSubsystemOrchestrator,
    MissionRuntime,
    RuntimeVersions,
)
from cti_services.governance_client import GovernanceUnavailableError


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class MemoryDb:
    def __init__(self):
        self.tasks = {
            "task-a": {
                "id": 1,
                "task_id": "task-a",
                "mission_id": "mission-27",
                "assigned_component": "cti_acquisition_freshness_agent",
                "task_type": "SYNC_SELECTED_CTI_SOURCE",
                "status": "COMMITTED",
                "authorization_mode": "REQUIRED",
                "policy_decision_id": "gdec-1",
                "authorization_request_id": "greq-1",
                "policy_decision_hash": "a" * 64,
                "scope_contract_id": "scope-27",
                "scope_version": 1,
                "policy_set_id": "default-policy",
                "revocation_status": None,
                "revoked_at": None,
            },
            "task-b": {
                "id": 2,
                "task_id": "task-b",
                "mission_id": "mission-27",
                "assigned_component": "cti_acquisition_freshness_agent",
                "task_type": "SYNC_SELECTED_CTI_SOURCE",
                "status": "COMMITTED",
                "authorization_mode": "REQUIRED",
                "policy_decision_id": "gdec-2",
                "authorization_request_id": "greq-2",
                "policy_decision_hash": "b" * 64,
                "scope_contract_id": "scope-27",
                "scope_version": 1,
                "policy_set_id": "default-policy",
                "revocation_status": None,
                "revoked_at": None,
            },
            "task-c": {
                "id": 3,
                "task_id": "task-c",
                "mission_id": "mission-27",
                "assigned_component": "cti_acquisition_freshness_agent",
                "task_type": "SYNC_SELECTED_CTI_SOURCE",
                "status": "COMPLETED",
                "authorization_mode": "REQUIRED",
                "policy_decision_id": "gdec-1",
                "authorization_request_id": "greq-1",
                "policy_decision_hash": "a" * 64,
                "scope_contract_id": "scope-27",
                "scope_version": 1,
                "policy_set_id": "default-policy",
                "revocation_status": None,
                "revoked_at": None,
            },
        }
        self.calls = []

    def table_exists(self, name):
        return name == "cti_task_contracts"

    def has_column(self, table, column):
        return table == "cti_task_contracts" and column == "revocation_status"

    def fetch_all(self, sql, params=None):
        params = params or {}
        if "FROM cti_task_contracts" in sql and "policy_decision_id" in sql:
            rows = [
                deepcopy(row)
                for row in self.tasks.values()
                if row["mission_id"] == params.get("mission_id")
                and row["policy_decision_id"] == params.get("decision_id")
                and row["authorization_mode"] == "REQUIRED"
            ]
            return sorted(rows, key=lambda row: row["id"])
        return []

    def fetch_one(self, sql, params=None):
        params = params or {}
        if "FROM cti_task_contracts" in sql:
            row = self.tasks.get(params.get("task_id"))
            return deepcopy(row) if row else None
        return None

    def execute(self, sql, params=None):
        params = dict(params or {})
        self.calls.append((sql, params))
        task_id = params.get("task_id")
        row = self.tasks.get(task_id) if task_id else None
        if row is None:
            return 1

        if "SET revocation_id=" in sql:
            if row["policy_decision_id"] != params.get("decision_id"):
                return 0
            prior = row["status"]
            row["revocation_id"] = params.get("revocation_id")
            row["revocation_event_id"] = params.get("revocation_event_id")
            row["revocation_status"] = params.get("revocation_status")
            row["revocation_reason"] = params.get("revocation_reason")
            row["revoked_at"] = params.get("revoked_at")
            if prior == "COMMITTED":
                row["status"] = "BLOCKED_REVOKED"
            elif prior == "RUNNING":
                row["status"] = "REVOCATION_PENDING_STOP"
            return 1

        if "SET status='RUNNING'" in sql and "revocation_status" in sql:
            if row["status"] != "COMMITTED" or row.get("revocation_status") or row.get("revoked_at"):
                return 0
            row["status"] = "RUNNING"
            return 1

        if "SET status='CANCELLED_REVOKED'" in sql:
            if not row.get("revocation_status"):
                return 0
            row["status"] = "CANCELLED_REVOKED"
            return 1
        return 1


class RevokedGovernance:
    def __init__(self, *, status="REVOKED", unavailable=False):
        self.status = status
        self.unavailable = unavailable

    def get_policy_decision(self, decision_id, **kwargs):
        if self.unavailable:
            raise GovernanceUnavailableError("governance offline")
        return {
            "decision_id": decision_id,
            "request_id": "greq-1",
            "mission_id": "mission-27",
            "decision": "ALLOW",
            "reason_codes": [],
            "constraints": {},
            "requires_human_approval": False,
            "valid_from": "2026-08-18T00:00:00+00:00",
            "valid_until": "2026-08-19T00:00:00+00:00",
            "decision_hash": "a" * 64,
            "decision_status": self.status,
            "scope_contract_id": "scope-27",
            "scope_version": 1,
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }


class Stage27GranularRevocationTests:
    pass


def make_orchestrator(governance):
    db = MemoryDb()
    orch = CtiSubsystemOrchestrator(
        db=db,
        registry=AlwaysOnRegistry(),
        governance_client=governance,
    )
    runtime = MissionRuntime(
        mission_id="mission-27",
        plan_id="plan-27",
        versions=RuntimeVersions(),
        scan_payload={},
        mission_context={},
        policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime
    return orch, db, runtime


def revocation_payload():
    return {
        "revocation_id": "grevoke-27",
        "governance_event_id": "gevent-27",
        "decision_id": "gdec-1",
        "request_id": "greq-1",
        "mission_id": "mission-27",
        "decision_hash": "a" * 64,
        "decision_status": "REVOKED",
        "scope_contract_id": "scope-27",
        "scope_version": 1,
        "reason": "operator revoke",
        "revoked_by": "operator-27",
        "revoked_at": "2026-08-18T00:10:00+00:00",
        "authority": "aptsGSS",
        "authority_component": "GOV-PLANE",
        "revocation_scope": "POLICY_DECISION",
    }


def test_exact_decision_revocation_invalidates_only_bound_tasks():
    orch, db, runtime = make_orchestrator(RevokedGovernance())
    projection = orch._project_authorization_revocation(
        runtime,
        mission_id="mission-27",
        payload=revocation_payload(),
        source_component="GOV-PLANE",
        event_id="event-local-27",
    )

    assert projection["verification_status"] == "VERIFIED_REVOKED"
    assert projection["affected_task_count"] == 2
    assert projection["active_affected_count"] == 1
    assert db.tasks["task-a"]["status"] == "BLOCKED_REVOKED"
    assert db.tasks["task-a"]["revocation_status"] == "VERIFIED_REVOKED"
    assert db.tasks["task-b"]["status"] == "COMMITTED"  # unrelated decision survives
    assert db.tasks["task-b"]["revocation_status"] is None
    assert db.tasks["task-c"]["status"] == "COMPLETED"  # history is not rewritten
    assert db.tasks["task-c"]["revocation_status"] == "VERIFIED_REVOKED"
    assert "task-a" in runtime.revoked_task_ids
    assert "task-b" not in runtime.revoked_task_ids
    assert runtime.policy_context["scope_allowed"] is True


def test_false_or_stale_revocation_event_is_rejected_when_authority_still_active():
    orch, db, runtime = make_orchestrator(RevokedGovernance(status="ACTIVE"))
    projection = orch._project_authorization_revocation(
        runtime,
        mission_id="mission-27",
        payload=revocation_payload(),
        source_component="GOV-PLANE",
        event_id="event-local-27",
    )
    assert projection["verification_status"] == "REJECTED_AUTHORITATIVE_STATUS_ACTIVE"
    assert projection["active_affected_count"] == 0
    assert db.tasks["task-a"]["status"] == "COMMITTED"
    assert db.tasks["task-b"]["status"] == "COMMITTED"


def test_governance_unavailable_revocation_fails_closed_only_for_exact_binding():
    orch, db, runtime = make_orchestrator(RevokedGovernance(unavailable=True))
    projection = orch._project_authorization_revocation(
        runtime,
        mission_id="mission-27",
        payload=revocation_payload(),
        source_component="GOV-PLANE",
        event_id="event-local-27",
    )
    assert projection["verification_status"] == "FAIL_CLOSED_GOVERNANCE_UNAVAILABLE"
    assert db.tasks["task-a"]["status"] == "BLOCKED_REVOKED"
    assert db.tasks["task-b"]["status"] == "COMMITTED"


def test_atomic_running_transition_cannot_cross_revocation_projection():
    orch, db, runtime = make_orchestrator(RevokedGovernance())
    orch._project_authorization_revocation(
        runtime,
        mission_id="mission-27",
        payload=revocation_payload(),
        source_component="GOV-PLANE",
        event_id="event-local-27",
    )
    assert orch._transition_authorized_task_to_running("task-a") is False
    assert orch._transition_authorized_task_to_running("task-b") is True


def test_granular_reactive_action_does_not_cancel_whole_mission():
    orch, db, runtime = make_orchestrator(RevokedGovernance())
    projection = orch._project_authorization_revocation(
        runtime,
        mission_id="mission-27",
        payload=revocation_payload(),
        source_component="GOV-PLANE",
        event_id="event-local-27",
    )
    proposal = orch.handle_reactive_event(
        "mission-27",
        {"event_type": "AUTHORIZATION_REVOKED", "cti_revocation_projection": projection},
        runtime.versions,
    )
    orch._apply_reactive_action(runtime, proposal)
    assert runtime.status == "RUNNING"
    assert runtime.policy_context["scope_allowed"] is True
    assert runtime.plan_id != "plan-27"

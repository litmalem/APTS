from __future__ import annotations

import os
import sys
import types
from copy import deepcopy
from datetime import datetime, timedelta, timezone

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

from cti_services.common import sha256_object
from cti_services.contracts import (
    AUTHORIZATION_REQUIRED,
    PolicyDecisionBinding,
    TaskContract,
    policy_decision_hash_payload,
)
from cti_services.cti_subsystem_orchestrator import (
    CtiSubsystemOrchestrator,
    MissionRuntime,
    RuntimeVersions,
)


class AlwaysOnRegistry:
    def is_enabled(self, key):
        return True

    def update_status(self, *args, **kwargs):
        return None


class CaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return name in {"cti_action_proposals", "cti_task_contracts"}

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1


class RevalidationGovernance:
    def __init__(self, *, valid=True):
        self.valid = valid

    def revalidate_policy_decision(self, **kwargs):
        return {
            "revalidation_id": "greval-285",
            "status": "VALID" if self.valid else "INVALID",
            "valid": self.valid,
            "execution_authorized": self.valid,
            "reason_codes": [] if self.valid else ["POLICY_DECISION_REVOKED"],
            "decision_id": kwargs["decision_id"],
            "request_id": kwargs["request_id"],
            "mission_id": kwargs["mission_id"],
            "decision_hash": kwargs["decision_hash"],
            "decision_status": "ACTIVE" if self.valid else "REVOKED",
            "scope_version": kwargs.get("scope_version"),
            "policy_version": kwargs.get("policy_version"),
        }


class RevocationDb:
    def __init__(self):
        self.task = {
            "task_id": "task-revoked-285",
            "mission_id": "mission-285",
            "assigned_component": "cti_acquisition_freshness_agent",
            "task_type": "SYNC_SELECTED_CTI_SOURCE",
            "status": "COMMITTED",
            "trace_id": "proposal-revoked-285",
            "authorization_mode": "REQUIRED",
            "policy_decision_id": "gdec-285",
            "authorization_request_id": "greq-285",
            "policy_decision_hash": "a" * 64,
            "scope_contract_id": "scope-285",
            "scope_version": 2,
            "policy_set_id": "default-policy",
            "pre_dispatch_revalidation_id": "greval-revoked-285",
            "revocation_status": None,
            "revoked_at": None,
        }

    def table_exists(self, name):
        return name == "cti_task_contracts"

    def has_column(self, table, column):
        return table == "cti_task_contracts" and column == "revocation_status"

    def fetch_all(self, sql, params=None):
        params = params or {}
        if (
            "FROM cti_task_contracts" in sql
            and params.get("mission_id") == self.task["mission_id"]
            and params.get("decision_id") == self.task["policy_decision_id"]
        ):
            return [deepcopy(self.task)]
        return []

    def execute(self, sql, params=None):
        if "SET revocation_id=" in sql:
            self.task["status"] = "BLOCKED_REVOKED"
            self.task["revocation_status"] = (params or {}).get("revocation_status")
        return 1


class RevokedGovernance:
    def get_policy_decision(self, decision_id, **kwargs):
        return {
            "decision_id": decision_id,
            "request_id": "greq-285",
            "mission_id": "mission-285",
            "decision": "ALLOW",
            "reason_codes": [],
            "constraints": {},
            "requires_human_approval": False,
            "valid_from": "2026-08-19T00:00:00+00:00",
            "valid_until": "2026-08-20T00:00:00+00:00",
            "decision_hash": "a" * 64,
            "decision_status": "REVOKED",
            "scope_contract_id": "scope-285",
            "scope_version": 2,
            "policy_set_id": "default-policy",
            "policy_version": 8,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }


def _decision():
    now = datetime.now(timezone.utc)
    decision = {
        "request_id": "greq-285",
        "decision_id": "gdec-285",
        "mission_id": "mission-285",
        "decision": "ALLOW",
        "reason_codes": ["ACTION_CONSTRAINT_ALLOW"],
        "constraints": {"read_only": True},
        "requires_human_approval": False,
        "approval_request_id": None,
        "valid_from": (now - timedelta(seconds=5)).isoformat(),
        "valid_until": (now + timedelta(minutes=5)).isoformat(),
        "policy_set_id": "default-policy",
        "policy_version": 8,
        "scope_contract_id": "scope-285",
        "scope_version": 2,
        "authority": "aptsGSS",
        "authority_component": "GOV-PLANE",
        "decision_status": "ACTIVE",
        "authorization_request": {
            "mission_id": "mission-285",
            "scope_contract_id": "scope-285",
            "subject_component": "CTI-A02",
            "action_class": "CTI_SOURCE_READ",
            "action_name": "INCREMENTAL_FETCH",
            "resource_type": "CTI_SOURCE",
            "resource_value": "nvd-cve",
        },
    }
    decision["decision_hash"] = sha256_object(policy_decision_hash_payload(decision))
    return decision


def _binding():
    return PolicyDecisionBinding.from_policy_decision(
        _decision(),
        expected_mission_id="mission-285",
        expected_action_class="CTI_SOURCE_READ",
        expected_action_name="INCREMENTAL_FETCH",
        expected_resource_type="CTI_SOURCE",
        expected_resource_value="nvd-cve",
        expected_scope_contract_id="scope-285",
    )


def _required_contract():
    return TaskContract(
        task_id="task-auth-285",
        mission_id="mission-285",
        plan_id="plan-285",
        assigned_component="cti_acquisition_freshness_agent",
        task_type="SYNC_SELECTED_CTI_SOURCE",
        priority=90,
        input_refs=["nvd-cve"],
        local_guard={"decision": "ALLOW", "reasons": []},
        plan_version=3,
        policy_version="8",
        state_version=4,
        trace_id="proposal-auth-285",
        authorization_mode=AUTHORIZATION_REQUIRED,
        governance=_binding(),
    )


def _events(orch):
    result = []
    while True:
        event = orch.event_bus.pop()
        if event is None:
            return result
        result.append(event)


def test_internal_dispatch_and_completion_propagate_taskcontract_lineage():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    orch.asset_cpe.profile_scan = lambda payload, mission_id: {
        "status": "completed",
        "asset_profiles": [{"asset_profile_id": "assetprof-285"}],
        "cpe_claims": [],
    }
    runtime = MissionRuntime(
        mission_id="mission-internal-285",
        plan_id="plan-internal-285",
        versions=RuntimeVersions(state_version=1, plan_version=1, policy_version="8"),
        scan_payload={"target_url": "http://127.0.0.1:3000"},
        mission_context={},
        policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime

    orch._on_pipeline_advance({"mission_id": runtime.mission_id, "payload": {}})
    events = _events(orch)
    committed = next(e for e in events if e["event_type"] == "TASK_COMMITTED")
    dispatched = next(e for e in events if e["event_type"] == "TASK_DISPATCHED")
    completed = next(e for e in events if e["event_type"] == "TASK_COMPLETED")

    for event in (dispatched, completed):
        assert event["trace_id"] == committed["trace_id"]
        assert event["proposal_id"] == committed["proposal_id"]
        assert event["task_id"] == committed["task_id"]
        assert event["policy_decision_id"] is None
        assert event["authorization_request_id"] is None
        assert event["revalidation_id"] is None


def test_internal_failure_propagates_same_lineage():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())

    def fail_runner(payload, mission_id):
        raise RuntimeError("stage285-test-failure")

    orch.asset_cpe.profile_scan = fail_runner
    runtime = MissionRuntime(
        mission_id="mission-failure-285",
        plan_id="plan-failure-285",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={"target_url": "http://127.0.0.1:3000"},
        mission_context={},
        policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime

    orch._on_pipeline_advance({"mission_id": runtime.mission_id, "payload": {}})
    events = _events(orch)
    committed = next(e for e in events if e["event_type"] == "TASK_COMMITTED")
    failed = next(e for e in events if e["event_type"] == "TASK_FAILED")
    assert failed["trace_id"] == committed["trace_id"]
    assert failed["proposal_id"] == committed["proposal_id"]
    assert failed["task_id"] == committed["task_id"]


def test_revalidation_success_exposes_required_business_lineage():
    orch = CtiSubsystemOrchestrator(
        db=CaptureDb(),
        registry=AlwaysOnRegistry(),
        governance_client=RevalidationGovernance(valid=True),
    )
    runtime = MissionRuntime(
        mission_id="mission-285",
        plan_id="plan-285",
        versions=RuntimeVersions(state_version=4, plan_version=3, policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    contract = _required_contract()
    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["valid"] is True
    event = next(e for e in _events(orch) if e["event_type"] == "TASK_AUTHORIZATION_REVALIDATED")
    assert event["trace_id"] == "proposal-auth-285"
    assert event["proposal_id"] == "proposal-auth-285"
    assert event["task_id"] == "task-auth-285"
    assert event["policy_decision_id"] == "gdec-285"
    assert event["authorization_request_id"] == "greq-285"
    assert event["revalidation_id"] == "greval-285"


def test_revalidation_block_exposes_same_required_lineage():
    orch = CtiSubsystemOrchestrator(
        db=CaptureDb(),
        registry=AlwaysOnRegistry(),
        governance_client=RevalidationGovernance(valid=False),
    )
    runtime = MissionRuntime(
        mission_id="mission-285",
        plan_id="plan-285",
        versions=RuntimeVersions(state_version=4, plan_version=3, policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    contract = _required_contract()
    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["valid"] is False
    event = next(e for e in _events(orch) if e["event_type"] == "TASK_DISPATCH_BLOCKED")
    assert event["trace_id"] == "proposal-auth-285"
    assert event["proposal_id"] == "proposal-auth-285"
    assert event["task_id"] == "task-auth-285"
    assert event["policy_decision_id"] == "gdec-285"
    assert event["authorization_request_id"] == "greq-285"
    assert event["revalidation_id"] == "greval-285"


def test_granular_revocation_task_events_use_durable_taskcontract_lineage():
    db = RevocationDb()
    orch = CtiSubsystemOrchestrator(
        db=db,
        registry=AlwaysOnRegistry(),
        governance_client=RevokedGovernance(),
    )
    runtime = MissionRuntime(
        mission_id="mission-285",
        plan_id="plan-285",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime
    payload = {
        "revocation_id": "grevoke-285",
        "governance_event_id": "gevent-285",
        "decision_id": "gdec-285",
        "request_id": "greq-285",
        "mission_id": "mission-285",
        "decision_hash": "a" * 64,
        "decision_status": "REVOKED",
        "scope_contract_id": "scope-285",
        "scope_version": 2,
        "reason": "stage285 revoke",
        "revoked_by": "operator-285",
        "revoked_at": "2026-08-19T01:00:00+00:00",
        "revocation_scope": "POLICY_DECISION",
    }
    projection = orch._project_authorization_revocation(
        runtime,
        mission_id="mission-285",
        payload=payload,
        source_component="GOV-PLANE",
        event_id="event-ingress-285",
    )
    proposal = orch.handle_reactive_event(
        "mission-285",
        {"event_type": "AUTHORIZATION_REVOKED", "cti_revocation_projection": projection},
        runtime.versions,
    )
    orch._apply_reactive_action(runtime, proposal)
    events = _events(orch)
    for event_type in ("TASK_AUTHORIZATION_REVOKED", "TASK_DISPATCH_BLOCKED"):
        event = next(e for e in events if e["event_type"] == event_type)
        assert event["trace_id"] == "proposal-revoked-285"
        assert event["proposal_id"] == "proposal-revoked-285"
        assert event["task_id"] == "task-revoked-285"
        assert event["policy_decision_id"] == "gdec-285"
        assert event["authorization_request_id"] == "greq-285"
        assert event["revalidation_id"] == "greval-revoked-285"

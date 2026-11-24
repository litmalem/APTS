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
            "revalidation_id": "greval-286",
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
            "task_id": "task-revoked-286",
            "mission_id": "mission-286",
            "assigned_component": "cti_acquisition_freshness_agent",
            "task_type": "SYNC_SELECTED_CTI_SOURCE",
            "status": "COMMITTED",
            "trace_id": "proposal-revoked-286",
            "authorization_mode": "REQUIRED",
            "policy_decision_id": "gdec-286",
            "authorization_request_id": "greq-286",
            "policy_decision_hash": "a" * 64,
            "scope_contract_id": "scope-286",
            "scope_version": 2,
            "policy_set_id": "default-policy",
            "pre_dispatch_revalidation_id": "greval-revoked-286",
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
            "request_id": "greq-286",
            "mission_id": "mission-286",
            "decision": "ALLOW",
            "reason_codes": [],
            "constraints": {},
            "requires_human_approval": False,
            "valid_from": "2026-08-19T00:00:00+00:00",
            "valid_until": "2026-08-20T00:00:00+00:00",
            "decision_hash": "a" * 64,
            "decision_status": "REVOKED",
            "scope_contract_id": "scope-286",
            "scope_version": 2,
            "policy_set_id": "default-policy",
            "policy_version": 8,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }


def _decision():
    now = datetime.now(timezone.utc)
    decision = {
        "request_id": "greq-286",
        "decision_id": "gdec-286",
        "mission_id": "mission-286",
        "decision": "ALLOW",
        "reason_codes": ["ACTION_CONSTRAINT_ALLOW"],
        "constraints": {"read_only": True},
        "requires_human_approval": False,
        "approval_request_id": None,
        "valid_from": (now - timedelta(seconds=5)).isoformat(),
        "valid_until": (now + timedelta(minutes=5)).isoformat(),
        "policy_set_id": "default-policy",
        "policy_version": 8,
        "scope_contract_id": "scope-286",
        "scope_version": 2,
        "authority": "aptsGSS",
        "authority_component": "GOV-PLANE",
        "decision_status": "ACTIVE",
        "authorization_request": {
            "mission_id": "mission-286",
            "scope_contract_id": "scope-286",
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
        expected_mission_id="mission-286",
        expected_action_class="CTI_SOURCE_READ",
        expected_action_name="INCREMENTAL_FETCH",
        expected_resource_type="CTI_SOURCE",
        expected_resource_value="nvd-cve",
        expected_scope_contract_id="scope-286",
    )


def _required_contract():
    return TaskContract(
        task_id="task-auth-286",
        mission_id="mission-286",
        plan_id="plan-286",
        assigned_component="cti_acquisition_freshness_agent",
        task_type="SYNC_SELECTED_CTI_SOURCE",
        priority=90,
        input_refs=["nvd-cve"],
        local_guard={"decision": "ALLOW", "reasons": []},
        plan_version=3,
        policy_version="8",
        state_version=4,
        trace_id="proposal-auth-286",
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


def test_internal_task_forms_commit_dispatch_complete_causal_chain():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    orch.asset_cpe.profile_scan = lambda payload, mission_id: {
        "status": "completed",
        "asset_profiles": [{"asset_profile_id": "assetprof-286"}],
        "cpe_claims": [],
    }
    runtime = MissionRuntime(
        mission_id="mission-internal-286",
        plan_id="plan-internal-286",
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

    assert committed["causation_event_id"] is None
    assert dispatched["causation_event_id"] == committed["event_id"]
    assert completed["causation_event_id"] == dispatched["event_id"]
    assert orch._task_event_head(committed["task_id"]) == completed["event_id"]


def test_internal_failure_is_caused_by_dispatch():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())

    def fail_runner(payload, mission_id):
        raise RuntimeError("stage286-test-failure")

    orch.asset_cpe.profile_scan = fail_runner
    runtime = MissionRuntime(
        mission_id="mission-failure-286",
        plan_id="plan-failure-286",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={"target_url": "http://127.0.0.1:3000"},
        mission_context={},
        policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime

    orch._on_pipeline_advance({"mission_id": runtime.mission_id, "payload": {}})
    events = _events(orch)
    dispatched = next(e for e in events if e["event_type"] == "TASK_DISPATCHED")
    failed = next(e for e in events if e["event_type"] == "TASK_FAILED")
    assert failed["causation_event_id"] == dispatched["event_id"]


def test_revalidation_and_dispatch_can_continue_from_same_task_causal_head():
    orch = CtiSubsystemOrchestrator(
        db=CaptureDb(),
        registry=AlwaysOnRegistry(),
        governance_client=RevalidationGovernance(valid=True),
    )
    runtime = MissionRuntime(
        mission_id="mission-286",
        plan_id="plan-286",
        versions=RuntimeVersions(state_version=4, plan_version=3, policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    contract = _required_contract()
    orch._remember_task_event(contract.task_id, "event-commit-286")
    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["valid"] is True
    revalidated = next(e for e in _events(orch) if e["event_type"] == "TASK_AUTHORIZATION_REVALIDATED")
    assert revalidated["causation_event_id"] == "event-commit-286"
    assert orch._task_event_head(contract.task_id) == revalidated["event_id"]

    dispatched_id = orch._emit_task_lifecycle_event(
        runtime.mission_id,
        "TASK_DISPATCHED",
        orch.COMPONENT_ID,
        {"task_id": contract.task_id},
        runtime.versions,
        **orch._task_lineage_from_contract(contract, revalidation_id="greval-286"),
    )
    dispatched = next(e for e in _events(orch) if e["event_id"] == dispatched_id)
    assert dispatched["causation_event_id"] == revalidated["event_id"]


def test_revalidation_failure_block_is_caused_by_commit_head():
    orch = CtiSubsystemOrchestrator(
        db=CaptureDb(),
        registry=AlwaysOnRegistry(),
        governance_client=RevalidationGovernance(valid=False),
    )
    runtime = MissionRuntime(
        mission_id="mission-286",
        plan_id="plan-286",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    contract = _required_contract()
    orch._remember_task_event(contract.task_id, "event-commit-block-286")
    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["valid"] is False
    blocked = next(e for e in _events(orch) if e["event_type"] == "TASK_DISPATCH_BLOCKED")
    assert blocked["causation_event_id"] == "event-commit-block-286"


def test_external_governance_event_is_persisted_as_upstream_identity():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    runtime = MissionRuntime(
        mission_id="mission-policy-286",
        plan_id="plan-policy-286",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime
    published = orch.publish_external_event(
        runtime.mission_id,
        "POLICY_CHANGED",
        {"governance_event_id": "gevent-policy-286", "policy_version": "9"},
        source_component="GOV-PLANE",
    )
    assert published["upstream_event_id"] == "gevent-policy-286"


def test_revocation_forms_gevent_ingress_task_revoke_block_causal_chain():
    db = RevocationDb()
    orch = CtiSubsystemOrchestrator(
        db=db,
        registry=AlwaysOnRegistry(),
        governance_client=RevokedGovernance(),
    )
    runtime = MissionRuntime(
        mission_id="mission-286",
        plan_id="plan-286",
        versions=RuntimeVersions(policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={"scope_allowed": True},
    )
    orch._runtimes[runtime.mission_id] = runtime
    payload = {
        "revocation_id": "grevoke-286",
        "governance_event_id": "gevent-286",
        "decision_id": "gdec-286",
        "request_id": "greq-286",
        "mission_id": "mission-286",
        "decision_hash": "a" * 64,
        "decision_status": "REVOKED",
        "scope_contract_id": "scope-286",
        "scope_version": 2,
        "reason": "stage286 revoke",
        "revoked_by": "operator-286",
        "revoked_at": "2026-08-19T07:00:00+00:00",
        "revocation_scope": "POLICY_DECISION",
    }

    ingress = orch.publish_external_event(
        "mission-286",
        "AUTHORIZATION_REVOKED",
        payload,
        source_component="GOV-PLANE",
        severity="CRITICAL",
    )
    queued_ingress = orch.event_bus.pop()
    assert queued_ingress["event_id"] == ingress["event_id"]
    assert queued_ingress["upstream_event_id"] == "gevent-286"

    orch._on_reactive_trigger(queued_ingress)
    assert runtime.pending_reactive is not None
    orch._apply_reactive_action(runtime, runtime.pending_reactive)
    events = _events(orch)
    revoked = next(e for e in events if e["event_type"] == "TASK_AUTHORIZATION_REVOKED")
    blocked = next(e for e in events if e["event_type"] == "TASK_DISPATCH_BLOCKED")

    assert revoked["causation_event_id"] == queued_ingress["event_id"]
    assert revoked["upstream_event_id"] == "gevent-286"
    assert blocked["causation_event_id"] == revoked["event_id"]
    assert blocked["upstream_event_id"] == "gevent-286"

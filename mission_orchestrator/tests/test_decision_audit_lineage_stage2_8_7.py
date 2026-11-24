from __future__ import annotations

import json
import os
import sys
import types

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

from cti_services.contracts import (
    AUTHORIZATION_REQUIRED,
    PolicyDecisionBinding,
    TaskContract,
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


class CaptureAudit:
    def __init__(self):
        self.calls = []

    def append(self, **kwargs):
        self.calls.append(dict(kwargs))
        return f"audit-{len(self.calls)}"


class CaptureDb:
    def __init__(self):
        self.calls = []

    def table_exists(self, name):
        return name in {
            "cti_decision_traces",
            "cti_action_proposals",
            "cti_task_contracts",
        }

    def has_column(self, table, column):
        return table == "cti_task_contracts" and column in {
            "pre_dispatch_revalidation_status",
            "revocation_status",
        }

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1

    def fetch_one(self, sql, params=None):
        return None


class RevalidationGovernance:
    def revalidate_policy_decision(self, **kwargs):
        return {
            "revalidation_id": "greval-287",
            "governance_event_id": "gevent-reval-287",
            "status": "VALID",
            "valid": True,
            "execution_authorized": True,
            "reason_codes": [],
            "decision_id": kwargs["decision_id"],
            "request_id": kwargs["request_id"],
            "mission_id": kwargs["mission_id"],
            "decision_hash": kwargs["decision_hash"],
            "decision_status": "ACTIVE",
            "scope_version": kwargs.get("scope_version"),
            "policy_version": kwargs.get("policy_version"),
            "checked_at": "2026-08-19T14:00:00+00:00",
        }


def _trace_params(db: CaptureDb, decision_type: str):
    for sql, params in reversed(db.calls):
        if "INSERT INTO cti_decision_traces" in sql and params.get("decision_type") == decision_type:
            return params
    raise AssertionError(f"decision trace {decision_type} not found")


def _required_contract():
    binding = PolicyDecisionBinding(
        authority="aptsGSS",
        authority_component="GOV-PLANE",
        decision_id="gdec-287",
        request_id="greq-287",
        mission_id="mission-287",
        decision="ALLOW",
        decision_hash="a" * 64,
        decision_status="ACTIVE",
        policy_set_id="default-policy",
        policy_version=8,
        scope_contract_id="scope-287",
        scope_version=2,
        valid_from="2026-08-19T13:00:00+00:00",
        valid_until="2026-08-20T13:00:00+00:00",
        requires_human_approval=False,
        approval_request_id=None,
        reason_codes=["ALLOW"],
        constraints={"read_only": True},
        action_class="CTI_SOURCE_READ",
        action_name="INCREMENTAL_FETCH",
        resource_type="CTI_SOURCE",
        resource_value="nvd-cve",
        subject_component="CTI-A02",
        governance_event_id="gevent-issued-287",
        hash_verified=True,
    )
    return TaskContract(
        task_id="task-287",
        mission_id="mission-287",
        plan_id="plan-287",
        assigned_component="cti_acquisition_freshness_agent",
        task_type="SYNC_SELECTED_CTI_SOURCE",
        priority=50,
        input_refs=["nvd-cve"],
        local_guard={"decision": "ALLOW"},
        plan_version=3,
        policy_version="8",
        state_version=4,
        trace_id="proposal-287",
        authorization_mode=AUTHORIZATION_REQUIRED,
        governance=binding,
    )


def test_arbitration_trace_binds_selected_proposal_as_lineage_root():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry(), audit=audit)
    runtime = MissionRuntime(
        mission_id="mission-arb-287",
        plan_id="plan-arb-287",
        versions=RuntimeVersions(state_version=2, plan_version=1, policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={},
    )
    selected = {
        "proposal_id": "proposal-arb-287",
        "proposal_kind": "DELIBERATIVE",
        "reason_code": "DEPENDENCY_DAG_READY",
        "precedence": "DELIBERATIVE_OPTIMIZATION",
        "priority_utility": 0.8,
    }
    orch._persist_arbitration_trace(runtime, [selected], selected)

    params = _trace_params(db, "ARBITRATION")
    assert params["lineage_trace_id"] == "proposal-arb-287"
    assert params["proposal_id"] == "proposal-arb-287"
    assert params["task_id"] is None
    assert audit.calls[-1]["trace_id"] == params["trace_id"]


def test_task_commit_trace_and_audit_point_to_task_committed_event():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry(), audit=audit)
    versions = RuntimeVersions(state_version=2, plan_version=1, policy_version="8")
    proposal = {
        "proposal_id": "proposal-commit-287",
        "priority_utility": 0.5,
    }

    contract = orch._commit_task(
        "task-commit-287",
        proposal,
        {"decision": "ALLOW", "reasons": []},
        "mission-commit-287",
        "plan-commit-287",
        versions,
        "normalization_provenance_service",
        "NORMALIZE_CTI",
        [],
    )
    committed = next(e for e in iter(lambda: orch.event_bus.pop(), None) if e["event_type"] == "TASK_COMMITTED")
    params = _trace_params(db, "TASK_COMMIT")

    assert contract.trace_id == "proposal-commit-287"
    assert params["lineage_trace_id"] == contract.trace_id
    assert params["proposal_id"] == contract.trace_id
    assert params["task_id"] == contract.task_id
    assert params["policy_decision_id"] is None
    assert json.loads(params["execution_outcome"])["event_id"] == committed["event_id"]
    task_commit_audit = next(c for c in audit.calls if c["event_type"].endswith("task_commit"))
    assert task_commit_audit["trace_id"] == params["trace_id"]
    assert task_commit_audit["downstream_event_ref"] == committed["event_id"]


def test_pre_dispatch_revalidation_trace_binds_policy_request_revalidation_and_event():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(
        db=db,
        registry=AlwaysOnRegistry(),
        audit=audit,
        governance_client=RevalidationGovernance(),
    )
    runtime = MissionRuntime(
        mission_id="mission-287",
        plan_id="plan-287",
        versions=RuntimeVersions(state_version=4, plan_version=3, policy_version="8"),
        scan_payload={}, mission_context={}, policy_context={},
    )
    contract = _required_contract()
    orch._remember_task_event(contract.task_id, "event-commit-287")

    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["valid"] is True
    revalidated = next(e for e in iter(lambda: orch.event_bus.pop(), None) if e["event_type"] == "TASK_AUTHORIZATION_REVALIDATED")
    params = _trace_params(db, "PRE_DISPATCH_REVALIDATION")

    assert params["lineage_trace_id"] == "proposal-287"
    assert params["task_id"] == "task-287"
    assert params["policy_decision_id"] == "gdec-287"
    assert params["authorization_request_id"] == "greq-287"
    assert params["revalidation_id"] == "greval-287"
    assert json.loads(params["execution_outcome"])["event_id"] == revalidated["event_id"]
    reval_audit = next(c for c in audit.calls if c["event_type"].endswith("pre_dispatch_revalidation"))
    assert reval_audit["trace_id"] == params["trace_id"]
    assert reval_audit["downstream_event_ref"] == revalidated["event_id"]


def test_task_result_trace_and_audit_preserve_business_lineage():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry(), audit=audit)
    versions = RuntimeVersions(state_version=5, plan_version=3, policy_version="8")

    event_id = orch._emit_task_lifecycle_event(
        "mission-result-287",
        "TASK_COMPLETED",
        "asset_profiling_cpe_resolution_service",
        {"task_id": "task-result-287", "component": "asset_profiling_cpe_resolution_service"},
        versions,
        trace_id="proposal-result-287",
        proposal_id="proposal-result-287",
        task_id="task-result-287",
    )
    params = _trace_params(db, "TASK_RESULT")

    assert params["lineage_trace_id"] == "proposal-result-287"
    assert params["proposal_id"] == "proposal-result-287"
    assert params["task_id"] == "task-result-287"
    # 2.8.7.1: long service keys are normalized to the canonical architecture
    # component_id before writing varchar(32) decision/audit columns.
    assert params["component_id"] == "CTI-S02"
    assert json.loads(params["observations"])["source_component"] == "asset_profiling_cpe_resolution_service"
    assert json.loads(params["execution_outcome"])["event_id"] == event_id
    result_audit = next(c for c in audit.calls if c["event_type"].endswith("task_result"))
    assert result_audit["trace_id"] == params["trace_id"]
    assert result_audit["component_id"] == "CTI-S02"
    assert result_audit["downstream_event_ref"] == event_id


def test_revocation_decision_trace_keeps_causation_and_upstream_event_identity():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry(), audit=audit)
    versions = RuntimeVersions(state_version=6, plan_version=3, policy_version="8")

    event_id = orch._emit_task_lifecycle_event(
        "mission-revoke-287",
        "TASK_AUTHORIZATION_REVOKED",
        orch.COMPONENT_ID,
        {
            "task_id": "task-revoke-287",
            "policy_decision_id": "gdec-revoke-287",
            "revocation_id": "grevoke-287",
        },
        versions,
        causation_event_id="event-ingress-287",
        upstream_event_id="gevent-287",
        trace_id="proposal-revoke-287",
        proposal_id="proposal-revoke-287",
        task_id="task-revoke-287",
        policy_decision_id="gdec-revoke-287",
        authorization_request_id="greq-revoke-287",
    )
    params = _trace_params(db, "AUTHORIZATION_REVOCATION")
    outcome = json.loads(params["execution_outcome"])

    assert params["lineage_trace_id"] == "proposal-revoke-287"
    assert params["policy_decision_id"] == "gdec-revoke-287"
    assert outcome["event_id"] == event_id
    assert outcome["causation_event_id"] == "event-ingress-287"
    assert outcome["upstream_event_id"] == "gevent-287"
    rev_audit = next(c for c in audit.calls if c["event_type"].endswith("authorization_revocation"))
    assert rev_audit["trace_id"] == params["trace_id"]
    assert rev_audit["downstream_event_ref"] == event_id

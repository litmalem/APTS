from __future__ import annotations

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

from cti_services.contracts import AUTHORIZATION_REQUIRED, PolicyDecisionBinding
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
        return name in {"cti_decision_traces", "cti_action_proposals", "cti_task_contracts"}

    def has_column(self, table, column):
        if table == "cti_task_contracts":
            return column in {
                "pre_dispatch_revalidation_status",
                "revocation_status",
                "authorization_governance_event_id",
                "pre_dispatch_governance_event_id",
            }
        return True

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return 1

    def fetch_one(self, sql, params=None):
        return None


class RevalidationGovernance:
    def revalidate_policy_decision(self, **kwargs):
        return {
            "revalidation_id": "greval-288",
            "governance_event_id": "gevent-reval-288",
            "status": "VALID",
            "valid": True,
            "execution_authorized": True,
            "reason_codes": ["POLICY_DECISION_STILL_VALID"],
            "decision_id": kwargs["decision_id"],
            "request_id": kwargs["request_id"],
            "mission_id": kwargs["mission_id"],
            "decision_hash": kwargs["decision_hash"],
            "decision_status": "ACTIVE",
            "scope_version": kwargs.get("scope_version"),
            "current_scope_version": kwargs.get("scope_version"),
            "policy_version": kwargs.get("policy_version"),
            "current_policy_version": kwargs.get("policy_version"),
            "checked_at": "2026-08-20T00:00:00+00:00",
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
        }


def _binding():
    return PolicyDecisionBinding(
        authority="aptsGSS",
        authority_component="GOV-PLANE",
        decision_id="gdec-288",
        request_id="greq-288",
        mission_id="mission-288",
        decision="ALLOW",
        decision_hash="a" * 64,
        decision_status="ACTIVE",
        policy_set_id="default-policy",
        policy_version=1,
        scope_contract_id="scope-288",
        scope_version=1,
        valid_from="2026-08-19T00:00:00+00:00",
        valid_until="2026-08-21T00:00:00+00:00",
        requires_human_approval=False,
        approval_request_id=None,
        reason_codes=["ALLOW"],
        constraints={"read_only": True},
        action_class="CTI_SOURCE_READ",
        action_name="INCREMENTAL_FETCH",
        resource_type="CTI_SOURCE",
        resource_value="nvd-cve",
        subject_component="CTI-A02",
        governance_event_id="gevent-issued-288",
        hash_verified=True,
    )


def _trace_params(db, decision_type):
    for sql, params in reversed(db.calls):
        if "INSERT INTO cti_decision_traces" in sql and params.get("decision_type") == decision_type:
            return params
    raise AssertionError(f"trace {decision_type} not found")


def test_task_commit_carries_authoritative_issue_event_across_contract_event_trace_and_audit():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(db=db, registry=AlwaysOnRegistry(), audit=audit)
    versions = RuntimeVersions(state_version=2, plan_version=1, policy_version="1")

    contract = orch._commit_task(
        "task-288",
        {"proposal_id": "proposal-288", "priority_utility": 0.8},
        {"decision": "ALLOW", "reasons": []},
        "mission-288",
        "plan-288",
        versions,
        "cti_acquisition_freshness_agent",
        "SYNC_SELECTED_CTI_SOURCE",
        ["nvd-cve"],
        authorization_mode=AUTHORIZATION_REQUIRED,
        policy_decision_binding=_binding(),
    )

    task_insert = next(
        params for sql, params in db.calls
        if "INSERT INTO cti_task_contracts" in sql
    )
    assert task_insert["authorization_governance_event_id"] == "gevent-issued-288"

    committed = next(
        e for e in iter(lambda: orch.event_bus.pop(), None)
        if e["event_type"] == "TASK_COMMITTED"
    )
    assert committed["task_id"] == contract.task_id
    assert committed["upstream_event_id"] == "gevent-issued-288"

    trace = _trace_params(db, "TASK_COMMIT")
    assert trace["upstream_event_id"] == "gevent-issued-288"
    task_audit = next(c for c in audit.calls if c["event_type"].endswith("task_commit"))
    assert task_audit["upstream_event_ref"] == "gevent-issued-288"
    assert task_audit["downstream_event_ref"] == committed["event_id"]


def test_pre_dispatch_revalidation_carries_authoritative_revalidation_event_everywhere():
    db = CaptureDb()
    audit = CaptureAudit()
    orch = CtiSubsystemOrchestrator(
        db=db,
        registry=AlwaysOnRegistry(),
        audit=audit,
        governance_client=RevalidationGovernance(),
    )
    runtime = MissionRuntime(
        mission_id="mission-288",
        plan_id="plan-288",
        versions=RuntimeVersions(state_version=3, plan_version=1, policy_version="1"),
        scan_payload={}, mission_context={}, policy_context={},
    )
    contract = orch._commit_task(
        "task-reval-288",
        {"proposal_id": "proposal-reval-288", "priority_utility": 0.8},
        {"decision": "ALLOW", "reasons": []},
        "mission-288",
        "plan-288",
        runtime.versions,
        "cti_acquisition_freshness_agent",
        "SYNC_SELECTED_CTI_SOURCE",
        ["nvd-cve"],
        authorization_mode=AUTHORIZATION_REQUIRED,
        policy_decision_binding=_binding(),
    )
    # Drain commit event, while the orchestrator retains it as causal head.
    while orch.event_bus.pop() is not None:
        pass

    result = orch._pre_dispatch_revalidate(runtime, contract, contract.governance)
    assert result["governance_event_id"] == "gevent-reval-288"

    update = next(
        params for sql, params in db.calls
        if "pre_dispatch_governance_event_id" in sql and "UPDATE cti_task_contracts" in sql
    )
    assert update["governance_event_id"] == "gevent-reval-288"

    revalidated = next(
        e for e in iter(lambda: orch.event_bus.pop(), None)
        if e["event_type"] == "TASK_AUTHORIZATION_REVALIDATED"
    )
    assert revalidated["upstream_event_id"] == "gevent-reval-288"
    assert revalidated["causation_event_id"] is not None

    trace = _trace_params(db, "PRE_DISPATCH_REVALIDATION")
    assert trace["upstream_event_id"] == "gevent-reval-288"
    reval_audit = next(
        c for c in audit.calls if c["event_type"].endswith("pre_dispatch_revalidation")
    )
    assert reval_audit["upstream_event_ref"] == "gevent-reval-288"
    assert reval_audit["downstream_event_ref"] == revalidated["event_id"]


def test_governance_audit_event_ingress_is_durable_without_live_runtime():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    event = orch.publish_external_event(
        "mission-terminal-288",
        "POLICY_DECISION_REVALIDATED",
        {
            "governance_event_id": "gevent-late-288",
            "decision_id": "gdec-288",
            "revalidation_id": "greval-late-288",
        },
        source_component="GOV-PLANE",
    )
    assert event["event_type"] == "POLICY_DECISION_REVALIDATED"
    assert event["upstream_event_id"] == "gevent-late-288"


def test_scope_changed_governance_ingress_is_durable_without_live_runtime():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    event = orch.publish_external_event(
        "mission-terminal-scope",
        "SCOPE_CHANGED",
        {
            "governance_event_id": "gevent-scope-late",
            "scope_contract_id": "scope-late",
            "scope_version": 1,
        },
        source_component="GOV-PLANE",
    )
    assert event["event_type"] == "SCOPE_CHANGED"
    assert event["upstream_event_id"] == "gevent-scope-late"


def test_non_governance_external_event_still_requires_live_runtime():
    orch = CtiSubsystemOrchestrator(db=CaptureDb(), registry=AlwaysOnRegistry())
    try:
        orch.publish_external_event("missing-runtime", "SOURCE_DOWN", {})
    except KeyError:
        pass
    else:
        raise AssertionError("non-governance event must require a live mission runtime")
